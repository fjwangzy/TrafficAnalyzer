from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.core.ycx_connection import YcxPsycopgConnection, bind_query


def production(**changes):
    values = dict(_env_file=None, deployment_mode="production", app_runtime_profile="replay_v2",
                  db_name="xinchan", db_schema="ycx_drone", db_driver="psycopg", db_password="p@ss:/%#中文",
                  jwt_secret_key="private-production-jwt-value", bootstrap_admin_password="private-admin-value",
                  intranet_http_enabled=True, media_cookie_secure=False, cors_origins=["http://10.0.0.2:8009"])
    return Settings(**(values | changes))


def test_production_http_is_explicit_and_local_database_default_is_unchanged():
    settings = production()
    assert make_url(settings.database_url).password == "p@ss:/%#中文"
    assert settings.database_connect_args["options"] == "-csearch_path=ycx_drone,public"
    assert settings.kafka_consumer_group == "uav-platform-replay-v2"
    local = Settings(_env_file=None)
    assert (local.db_name, local.db_schema, local.db_driver) == ("road9", "public", "asyncpg")
    with pytest.raises(ValidationError, match="secure media"):
        production(intranet_http_enabled=False)
    with pytest.raises(ValidationError, match="CORS"):
        production(cors_origins=["http://*"])
    with pytest.raises(ValidationError, match="DB_SCHEMA"):
        production(db_schema="public;DROP SCHEMA public")
    with pytest.raises(ValidationError, match="canonical road9"):
        Settings(_env_file=None, app_runtime_profile="replay_v2", db_name="xinchan")


def test_ycx_parameter_binding_preserves_repeated_positions_casts_and_literal_percent():
    statement, values = bind_query("SELECT $2::text[], $1, $2, '90%'", ("x", ["a"]))
    assert statement == "SELECT %(p2)s::text[], %(p1)s, %(p2)s, '90%%'"
    assert values == {"p1": "x", "p2": ["a"]}


@pytest.mark.asyncio
async def test_vendor_ycx_transactions_require_readonly_and_do_not_swallow_errors():
    events = []

    @asynccontextmanager
    async def transaction():
        events.append("begin")
        try:
            yield
        except Exception:
            events.append("rollback")
            raise

    async def execute(statement):
        events.append(statement)

    connection = YcxPsycopgConnection(SimpleNamespace(transaction=transaction, execute=execute))
    with pytest.raises(ValueError, match="read-only"):
        async with connection.transaction():
            pass
    with pytest.raises(RuntimeError, match="query failure"):
        async with connection.transaction(readonly=True):
            raise RuntimeError("query failure")
    assert events == ["begin", "SET TRANSACTION READ ONLY", "rollback"]


@pytest.mark.asyncio
async def test_ycx_transaction_connection_errors_keep_existing_unavailable_error_contract():
    import asyncpg

    class VendorError(Exception):
        pass

    @asynccontextmanager
    async def unavailable():
        raise VendorError("connection closed")
        yield

    connection = YcxPsycopgConnection(SimpleNamespace(transaction=unavailable), error_type=VendorError)
    with pytest.raises(asyncpg.PostgresError, match="connection closed"):
        async with connection.transaction(readonly=True):
            pytest.fail("Unavailable connection entered a transaction")


def test_updated_production_account_and_namespace_keep_literal_password():
    settings = production(db_name='ycx_prod', db_schema='drone', db_user='sysdba', db_password='fixture!literal')
    url = make_url(settings.database_url)
    assert (url.username, url.password, url.database) == ('sysdba', 'fixture!literal', 'ycx_prod')
    assert settings.database_connect_args['options'] == '-csearch_path=drone,public'
    assert Settings(_env_file=None).db_name == 'road9'
