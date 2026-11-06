"""Deployment reports aggregate failures without exposing exception values."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

path = Path(__file__).resolve().parents[1] / "deploy/intranet/runtime_check.py"
spec = importlib.util.spec_from_file_location("runtime_preflight", path)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def test_failure_has_code_and_location_but_never_exception_text(capsys):
    preflight.progress("database.connect")
    secret = "postgresql://private-user:private-password@database/xinchan"
    try:
        raise AssertionError(secret)
    except AssertionError as exc:
        preflight.report_failure(exc)
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["ok"] is False
    issue = report["checks"][0]
    assert issue["code"] == "ENV_UNKNOWN"
    assert "test_failure_has_code" in issue["locations"][-1]
    assert secret not in captured.out + captured.err and "private-password" not in captured.out + captured.err


def test_libraries_only_keeps_legacy_json_contract(monkeypatch, capsys):
    monkeypatch.setattr(preflight.sys, "argv", ["runtime_check.py", "--libraries-only"])
    monkeypatch.setattr(preflight, "check_libraries", lambda: {"fixture": "passed"})
    assert preflight.main() == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"libraries": {"fixture": "passed"}}
    assert captured.err.strip() == "Preflight: libraries"


@pytest.mark.parametrize("origin", ["http://host/path", "http://user:private-password@host", "http://host/", " http://host"])
def test_configuration_rejects_non_origin_cors_without_echoing_value(monkeypatch, origin):
    from app.core import config
    monkeypatch.setattr(config, "settings", SimpleNamespace(db_name="xinchan", db_schema="ycx_drone", db_driver="psycopg",
        db_port=5866, doris_mysql_port=9030, cors_origins=[origin]))
    with pytest.raises(preflight.DiagnosticError) as captured:
        preflight.configuration()
    issue = preflight.explain("configuration", captured.value)
    assert issue["code"] == "CONFIG_CORS" and "private-password" not in json.dumps(issue)


@pytest.mark.asyncio
async def test_database_failure_does_not_hide_ycx_and_kafka(monkeypatch):
    visited = []
    async def database(report, settings):
        visited.append("database")
        raise TimeoutError("sensitive connection parameters")
    async def ycx(report, settings):
        visited.append("ycx")
        raise preflight.DiagnosticError("TABLE_NOT_FOUND", "缺表", "核对YCX")
    async def kafka(report, settings):
        visited.append("kafka")
        report.add("kafka.authentication_and_metadata", "passed")
    for name, function in (("database_checks", database), ("ycx_checks", ycx), ("kafka_checks", kafka)):
        monkeypatch.setattr(preflight, name, function)
    report = await preflight.check_connections(settings=SimpleNamespace())
    assert visited == ["database", "ycx", "kafka"]
    assert [item["status"] for item in report.checks] == ["failed", "warning", "passed"]
    assert report.checks[0]["code"] == "CONNECTION_TIMEOUT"


def test_model_failure_still_runs_connections_and_summary(monkeypatch, capsys):
    visited = []
    monkeypatch.setattr(preflight.sys, "argv", ["runtime_check.py"])
    monkeypatch.setattr(preflight, "check_libraries", lambda: {"fixture": "passed"})
    monkeypatch.setattr(preflight, "configuration", lambda: SimpleNamespace())
    monkeypatch.setattr(preflight, "model_checks", lambda report: report.error("models", ValueError("private")))
    monkeypatch.setattr(preflight, "resource_checks", lambda report: report.add("resources", "passed"))
    async def connections(report, settings):
        visited.append(True)
        report.add("kafka", "passed")
    monkeypatch.setattr(preflight, "check_connections", connections)
    assert preflight.main() == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert visited and report["summary"]["failed"] == 1
    assert report["checks"][-1]["stage"] == "kafka"
    assert "预检汇总" in captured.err and "private" not in captured.out + captured.err


@pytest.mark.asyncio
async def test_doris_roads_and_metrics_are_optional_and_never_connect_highgo(monkeypatch):
    from app.core import doris_connection
    visited = []
    async def query(settings, sql, *args):
        visited.append(sql)
        assert "road11" not in sql and sql.startswith("SELECT ")
        if "dim_link_info" in sql:
            raise preflight.DiagnosticError("DORIS_TABLE", "缺表", "核对Doris")
        return [{"version_id": "confirmed"}]
    monkeypatch.setattr(doris_connection, "query", query)
    settings = SimpleNamespace(doris_database="ycx_xc", ycx_metrics_backend="doris", ycx_road_version="")
    report = preflight.Report()
    await preflight.ycx_checks(report, settings)
    await preflight.doris_checks(report, settings)
    assert not report.failed
    assert len(visited) == 7
    assert sum(item["status"] == "warning" for item in report.checks) == 1
    assert any("dws_tfc_inter_index_m_5mi" in sql for sql in visited)
    assert any("dws_tfc_link_index_m_5mi" in sql for sql in visited)
    assert any("is_enabled=1" in sql for sql in visited)


def test_configuration_accepts_configured_production_database_and_schema(monkeypatch):
    from app.core import config
    settings = SimpleNamespace(db_name='ycx_prod', db_schema='drone', db_driver='psycopg',
                               db_port=5866, doris_mysql_port=9030, cors_origins=['http://10.0.0.1:8009'])
    monkeypatch.setattr(config, 'settings', settings)
    assert preflight.configuration() is settings


@pytest.mark.parametrize('database,schema', [('road9','drone'),('ycx_prod','public'),('ycx_prod','pg_catalog')])
def test_configuration_rejects_local_or_system_production_target(monkeypatch, database, schema):
    from app.core import config
    monkeypatch.setattr(config, 'settings', SimpleNamespace(db_name=database, db_schema=schema))
    with pytest.raises(preflight.DiagnosticError, match='CONFIG_DB_TARGET'):
        preflight.configuration()


@pytest.mark.asyncio
@pytest.mark.parametrize('reachable', [True, False])
async def test_native_preflight_checks_advertised_brokers_without_publishing(monkeypatch, reachable):
    monkeypatch.setattr("utils_local.kafka_topic_preflight.check_fixed_topics",lambda *args,**kwargs: [])
    import aiokafka
    import socket
    seen = []
    class Consumer:
        def __init__(self, **kwargs):
            assert kwargs['group_id'] is None and not kwargs['enable_auto_commit']
            self._client = SimpleNamespace(cluster=SimpleNamespace(brokers=lambda: [SimpleNamespace(host='advertised.invalid', port=9093)]))
        async def start(self):
            pass
        async def topics(self):
            return {'uav_system_metrics'}
        async def stop(self):
            seen.append('closed')
    class Connection:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    def probe(address, timeout):
        seen.append(address)
        if not reachable:
            raise OSError('must not reveal a private-password')
        return Connection()
    monkeypatch.setenv('TRAFFIC_NATIVE_OWNER', '/native')
    monkeypatch.setattr(aiokafka, 'AIOKafkaConsumer', Consumer)
    monkeypatch.setattr(socket, 'create_connection', probe)
    report = preflight.Report()
    settings = SimpleNamespace(kafka_bootstrap='bootstrap:9093', kafka_security_options={},
                               kafka_security_protocol='SASL_PLAINTEXT', kafka_sasl_mechanism='PLAIN')
    await preflight.kafka_checks(report, settings)
    assert ('advertised.invalid', 9093) in seen and seen[-1] == 'closed'
    assert report.failed == (not reachable)
    if not reachable:
        assert any(c.get('code') == 'KAFKA_ADVERTISED_UNREACHABLE' for c in report.checks)
    assert 'private-password' not in json.dumps(report.checks)
