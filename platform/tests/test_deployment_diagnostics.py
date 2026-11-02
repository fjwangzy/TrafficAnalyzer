import errno
import json
from types import SimpleNamespace

import pytest

from app.core.deployment_diagnostics import explain, Report, DiagnosticError


@pytest.mark.parametrize("state,expected", [("28P01", "DB_AUTH"), ("28000", "DB_ACCESS_RULE"),
    ("3D000", "DB_NOT_FOUND"), ("3F000", "SCHEMA_NOT_FOUND"), ("42501", "DB_PERMISSION"),
    ("42P01", "TABLE_NOT_FOUND"), ("42883", "FUNCTION_NOT_FOUND"), ("0A000", "DB_FEATURE_UNSUPPORTED"),
    ("53300", "DB_CONNECTION_LIMIT"), ("57014", "DB_QUERY_TIMEOUT"), ("42601", "DB_SQL_COMPATIBILITY")])
def test_sqlstate_survives_wrapping_without_printing_private_message(state, expected):
    inner = RuntimeError("postgresql://user:private-password@host/db")
    inner.sqlstate = state
    outer = RuntimeError("SQL and private parameters")
    outer.__cause__ = inner
    result = explain("database.connect", outer)
    assert result["code"] == expected and result["facts"]["sqlstate"] == state
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize("name,code", [("SaslAuthenticationFailedError", "KAFKA_AUTH"),
    ("UnsupportedSaslMechanismError", "KAFKA_MECHANISM"), ("TopicAuthorizationFailedError", "KAFKA_TOPIC_ACL"),
    ("GroupAuthorizationFailedError", "KAFKA_GROUP_ACL"), ("KafkaTimeoutError", "KAFKA_TIMEOUT")])
def test_kafka_errors_have_distinct_actions_without_echoing_credentials(name, code):
    error = type(name, (Exception,), {})("private-token-and-password")
    result = explain("kafka.authentication_and_metadata", error)
    assert result["code"] == code and "private" not in json.dumps(result)


@pytest.mark.parametrize("error,code", [(TimeoutError("private"), "CONNECTION_TIMEOUT"),
    (OSError(errno.ECONNREFUSED, "private"), "CONNECTION_REFUSED"),
    (OSError(errno.ENOSPC, "private"), "DISK_FULL"), (PermissionError("private"), "PATH_PERMISSION"),
    (RuntimeError("authentication method 13 not supported private"), "HIGHGO_AUTH_DRIVER"),
    (RuntimeError('password authentication failed for user private'), "DB_AUTH"),
    (RuntimeError('database "private" does not exist'), "DB_NOT_FOUND"),
    (RuntimeError('could not translate host name "private"'), "DNS_FAILED"),
    (RuntimeError("Ascend execute failed (code=507001) private"), "ASCEND_EXECUTION")])
def test_network_filesystem_and_native_codes_are_safe(error, code):
    result = explain("ascend.inference_960" if code == "ASCEND_EXECUTION" else "database.connect", error)
    assert result["code"] == code and "private" not in json.dumps(result)
    if code == "ASCEND_EXECUTION": assert result["facts"]["ascend_code"] == 507001


def test_reports_distinguish_failure_pending_and_skipped(capsys):
    report = Report()
    report.add("migrations", "pending_init", title="init-db待执行")
    report.skip("models", "设备不可用")
    report.error("schema", DiagnosticError("DB_SCHEMA_MISSING", "缺schema", "DBA预建", {"schema": "ycx_drone"}))
    report.emit()
    output = capsys.readouterr()
    data = json.loads(output.out)
    assert not data["ok"] and data["summary"]["failed"] == 1
    assert data["summary"]["skipped"] == 1 and data["summary"]["pending_init"] == 1
    assert "DBA预建" in output.err


@pytest.mark.parametrize("stage", ["configuration", "initialization.configuration"])
def test_invalid_integer_configuration_excludes_input(stage):
    from app.core.config import Settings
    with pytest.raises(Exception) as captured:
        Settings(_env_file=None, db_port="private-invalid-port")
    result = explain(stage, captured.value)
    assert result["code"] == "CONFIG_INTEGER"
    assert "db_port" in result["facts"]["fields"]
    assert "private-invalid-port" not in json.dumps(result)


def test_real_installed_kafka_exception_names_are_classified():
    errors = pytest.importorskip("aiokafka.errors")
    for name, expected in (("SaslAuthenticationFailed", "KAFKA_AUTH"),
                           ("AuthenticationFailedError", "KAFKA_AUTH"),
                           ("TransactionalIdAuthorizationFailed", "KAFKA_TRANSACTION_ACL")):
        result = explain("kafka.authentication_and_metadata", getattr(errors, name)("private"))
        assert result["code"] == expected and "private" not in json.dumps(result)


@pytest.mark.asyncio
async def test_explicit_initialization_preserves_original_error_while_local_contract_remains(monkeypatch):
    from app.core import database
    failure = RuntimeError("private driver details")
    failure.sqlstate = "42501"
    async def revision(): raise failure
    monkeypatch.setattr(database, "settings", SimpleNamespace(db_auto_migrate=True, deployment_mode="production"))
    monkeypatch.setattr(database, "database_revision", revision)
    with pytest.raises(RuntimeError) as captured:
        await database.init_db(raise_on_error=True)
    assert captured.value is failure
    # Local callers keep the established bool-return contract.
    assert await database.init_db() is False
