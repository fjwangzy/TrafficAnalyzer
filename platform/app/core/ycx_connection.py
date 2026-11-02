"""Libpq-backed read-only connection for existing YCX queries in production."""

import re
from contextlib import asynccontextmanager

import asyncpg
from app.core.deployment_diagnostics import DiagnosticError


async def active_road_version(connection, settings, explicit=None):
    version = explicit or getattr(settings, "ycx_road_version", "")
    if version:
        return version
    try:
        version = await connection.fetchval(
            "SELECT version_id FROM dim_data_version WHERE is_enable = 1 ORDER BY version_id DESC LIMIT 1"
        )
    except asyncpg.PostgresError as exc:
        raise DiagnosticError("YCX_VERSION_UNAVAILABLE", "路网版本元数据不可用，暂停自动选择版本",
                              "可在.env填写已确认的YCX_ROAD_VERSION，或导入时显式传入road_data_version；不猜测最新版本。") from exc
    if version is None:
        raise DiagnosticError("YCX_VERSION_UNAVAILABLE", "没有已启用的路网版本",
                              "设置已确认的YCX_ROAD_VERSION或暂不使用外部路网。")
    return version


def bind_query(query, values):
    # Only the project's static YCX SQL uses this positional-parameter boundary.
    query = query.replace("%", "%%")
    return re.sub(r"\$(\d+)", lambda m: f"%(p{m[1]})s", query), {
        f"p{index}": value for index, value in enumerate(values, 1)
    }


class YcxPsycopgConnection:
    def __init__(self, connection, *, error_type=()):
        self.connection = connection
        self.error_type = error_type

    @asynccontextmanager
    async def transaction(self, *, readonly=False):
        if not readonly:
            raise ValueError("YCX connections must be read-only")
        try:
            async with self.connection.transaction():
                await self.connection.execute("SET TRANSACTION READ ONLY")
                yield
        except self.error_type as exc:
            raise asyncpg.PostgresError(str(exc)) from exc

    async def fetch(self, query, *values):
        try:
            statement, params = bind_query(query, values)
            cursor = await self.connection.execute(statement, params or None)
            return await cursor.fetchall()
        except self.error_type as exc:
            raise asyncpg.PostgresError(str(exc)) from exc

    async def fetchrow(self, query, *values):
        rows = await self.fetch(query, *values)
        return rows[0] if rows else None

    async def fetchval(self, query, *values):
        row = await self.fetchrow(query, *values)
        return next(iter(row.values())) if row else None

    async def close(self):
        await self.connection.close()


async def connect_highgo(**kwargs):
    import psycopg
    from psycopg.rows import dict_row

    kwargs["dbname"] = kwargs.pop("database")
    kwargs["connect_timeout"] = int(kwargs.pop("timeout", 10))
    server_settings = kwargs.pop("server_settings", {})
    schema = server_settings.get("search_path", "public")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:,[A-Za-z_][A-Za-z0-9_]*)*", schema):
        raise ValueError("Invalid YCX search_path")
    try:
        connection = await psycopg.AsyncConnection.connect(
            **kwargs, options=f"-csearch_path={schema} -cdefault_transaction_read_only=on",
            row_factory=dict_row, autocommit=True,
        )
        try:
            names = ", ".join('"' + name + '"' for name in schema.split(","))
            await connection.execute("SET SESSION search_path TO " + names)
            await connection.execute("SET SESSION default_transaction_read_only=on")
        except BaseException:
            await connection.close()
            raise
    except psycopg.Error as exc:
        raise asyncpg.PostgresError(str(exc)) from exc
    return YcxPsycopgConnection(connection, error_type=psycopg.Error)
