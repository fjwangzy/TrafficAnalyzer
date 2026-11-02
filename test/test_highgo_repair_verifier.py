"""The repair refuses to start with the old parser, without opening a connection."""
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys

import pytest


@pytest.mark.parametrize("active", [True, False])
def test_repair_verifies_actual_runtime_and_migration_dialects(monkeypatch, capsys, active):
    template = (Path(__file__).resolve().parents[1] / "deploy/intranet/repair-highgo.sh.in").read_text()
    program = template.split("verify='", 1)[1].split("'\nrun ", 1)[0]

    class HighGoPsycopgDialect:
        def _get_server_version_info(self, response):
            assert response.exec_driver_sql("SHOW server_version_num").scalar_one() == "120007"
            return (12, 7)

    HighGoPsycopgDialect._get_server_version_info.__module__ = "app.core.highgo_dialect"
    dialect = HighGoPsycopgDialect() if active else SimpleNamespace(
        _get_server_version_info=lambda _: None)
    engine = SimpleNamespace(sync_engine=SimpleNamespace(dialect=dialect))
    config = ModuleType("app.core.config")
    config.__file__ = "/app/platform/app/core/config.py"
    config.settings = SimpleNamespace(database_url="fixture-only-not-used-to-connect")
    app, core = ModuleType("app"), ModuleType("app.core")
    app.core, core.config = core, config
    for name, value in {"app": app, "app.core": core, "app.core.config": config,
                        "app.core.database": SimpleNamespace(engine=engine),
                        "app.core.deployment_diagnostics": SimpleNamespace(Report=lambda: None),
                        "app.core.highgo_dialect": SimpleNamespace(HighGoPsycopgDialect=HighGoPsycopgDialect)}.items():
        monkeypatch.setitem(sys.modules, name, value)
    import sqlalchemy.ext.asyncio
    monkeypatch.setattr(sqlalchemy.ext.asyncio, "async_engine_from_config", lambda _: engine)
    monkeypatch.setattr(sys, "argv", ["verify", "init-db"])
    if active:
        exec(compile(program, "repair-verifier", "exec"), {})
        assert "VERIFIED" in capsys.readouterr().out
    else:
        with pytest.raises(SystemExit, match="1"):
            exec(compile(program, "repair-verifier", "exec"), {})
        output = capsys.readouterr().out
        assert "Verification failed" in output and "VERIFIED" not in output
        assert "LOADED_CONFIG:" in output and "LOADED_DIALECT:" in output


def test_startup_log_filter_preserves_only_controlled_diagnostics(monkeypatch, capsys):
    import io
    template = (Path(__file__).resolve().parents[1] / "deploy/intranet/repair-highgo.sh.in").read_text()
    program = template.split("filter='", 1)[1].split("'\n        for service", 1)[0]
    monkeypatch.setattr(sys, "stdin", io.StringIO(
        "OperationalError postgresql://user:private-password@host/db\n"
        "Invalid MineMap key private-map-key\n"
        "nginx: [emerg] private-details\n"
        "DIAGNOSTIC [DB_SCHEMA_MISSING] database.schema: 缺schema | 处理：DBA预建\n"))
    exec(compile(program, "startup-filter", "exec"), {})
    output = capsys.readouterr().out
    assert "MINEMAP_CONFIG" in output and "GATEWAY_CONFIG" in output and "DB_SCHEMA_MISSING" in output
    assert "private" not in output and "postgresql://" not in output
