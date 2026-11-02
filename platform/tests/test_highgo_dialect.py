from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_engine_from_config, create_async_engine

from app.core.config import Settings
from app.core.highgo_dialect import HighGoPsycopgDialect


def test_stock_dialect_reproduces_reported_assertion_on_vendor_banner():
    from sqlalchemy.dialects.postgresql.psycopg import PGDialectAsync_psycopg
    connection = SimpleNamespace(exec_driver_sql=lambda _: SimpleNamespace(
        scalar=lambda: "HighGo Database test fixture"))
    with pytest.raises(AssertionError):
        PGDialectAsync_psycopg()._get_server_version_info(connection)


@pytest.mark.parametrize("number,expected", [(90624, (9, 6, 24)), (100001, (10, 1)),
                                            (120007, (12, 7)), (140011, (14, 11))])
def test_version_uses_numeric_kernel_version_without_product_banner(number, expected):
    statements = []

    def execute(statement):
        statements.append(statement)
        return SimpleNamespace(scalar_one=lambda: str(number))

    assert HighGoPsycopgDialect()._get_server_version_info(SimpleNamespace(exec_driver_sql=execute)) == expected
    assert statements == ["SHOW server_version_num"]


@pytest.mark.parametrize("number", [None, "HighGo 6.0", "14.7", "0", "-1"])
def test_invalid_kernel_version_fails_without_guessing_or_echoing_response(number):
    connection = SimpleNamespace(exec_driver_sql=lambda _: SimpleNamespace(scalar_one=lambda: number))
    with pytest.raises(RuntimeError, match="numeric server_version_num"):
        HighGoPsycopgDialect()._get_server_version_info(connection)


def test_runtime_and_migration_engine_keep_custom_async_dialect_and_local_defaults():
    settings = Settings(_env_file=None, db_driver="psycopg", db_password="fixture-only")
    url = settings.database_url
    assert make_url(url).drivername == "postgresql+highgo_psycopg"
    assert Settings(_env_file=None).db_driver == "asyncpg"
    assert make_url(Settings(_env_file=None).database_url).drivername == "postgresql+asyncpg"
    assert make_url(url).get_dialect(_is_async=True) is HighGoPsycopgDialect
    pytest.importorskip("psycopg", reason="optional HighGo driver; exercised in the ARM64 production image")
    runtime = create_async_engine(url)
    migration = async_engine_from_config({"sqlalchemy.url": url})
    assert type(runtime.sync_engine.dialect) is HighGoPsycopgDialect
    assert type(migration.sync_engine.dialect) is HighGoPsycopgDialect
    assert runtime.sync_engine.dialect.is_async


def test_schema_hook_sets_session_before_initialization_and_restores_autocommit():
    events = []
    dialect = HighGoPsycopgDialect()
    url = make_url("postgresql+highgo_psycopg://fixture@localhost/xinchan?application_schema=ycx_drone")

    class Cursor:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            events.append("closed")
        def execute(self, sql):
            assert connection.autocommit
            events.append(sql)

    connection = SimpleNamespace(autocommit=False, cursor=Cursor, add_notice_handler=lambda _: None)
    dialect.on_connect_url(url)(connection)
    assert events == ['SET SESSION search_path TO "ycx_drone", public', "closed"]
    assert connection.autocommit is False
    with pytest.raises(ValueError, match="Invalid application schema"):
        dialect.on_connect_url(url.set(query={"application_schema": 'public;DROP SCHEMA public'}))


def test_schema_hook_restores_autocommit_when_setting_fails():
    class Cursor:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def execute(self, sql):
            raise RuntimeError("fixture failure")
    connection = SimpleNamespace(autocommit=False, cursor=Cursor, add_notice_handler=lambda _: None)
    dialect = HighGoPsycopgDialect()
    with pytest.raises(RuntimeError, match="fixture failure"):
        dialect.on_connect_url(make_url("postgresql+highgo_psycopg://fixture@localhost/xinchan"))(connection)
    assert connection.autocommit is False
