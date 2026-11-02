#!/usr/bin/env python3
"""Explicit one-shot schema migration; ordinary Platform startup never runs it."""

import asyncio
import os
import sys
from pathlib import Path

# Migrations live beside the source package, not in the installed wheel.
for candidate in Path(__file__).resolve().parents:
    if (candidate / "platform/app").is_dir():
        sys.path.insert(0, str(candidate / "platform"))
        break

os.environ["DB_AUTO_MIGRATE"] = "true"

from app.core.deployment_diagnostics import DiagnosticError, Report

_stage = "initialization.configuration"


async def main():
    global _stage
    from app.core.config import settings
    from app.core.database import init_db, init_replay_v2_db, validate_database, close_db
    from app.core.database import engine
    from sqlalchemy import text

    if settings.deployment_mode != "production" or not settings.db_name or settings.db_name == "road9" or settings.db_schema in {"public", "pg_catalog", "information_schema"}:
        raise DiagnosticError("INIT_CONFIGURATION", "初始化必须使用production和指定的独立业务库/schema", "核对DEPLOYMENT_MODE、DB_NAME及DB_SCHEMA，不修改本地road9配置。")
    try:
        _stage = "initialization.preconditions"
        async with engine.connect() as connection:
            actual = (await connection.execute(text("SELECT current_database(), current_schema()"))).one()
            enabled = await connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='timescaledb')"))
            if tuple(actual) != (settings.db_name, settings.db_schema):
                raise DiagnosticError("INIT_DB_TARGET", "初始化目标库/schema不正确", "核对DB_NAME/DB_SCHEMA、schema存在性与USAGE；不会向public建表。",
                                      {"actual_database": actual[0], "actual_schema": actual[1]})
            if not enabled and settings.db_timescale_required:
                raise DiagnosticError("TIMESCALE_MISSING", "初始化前未启用TimescaleDB", "由DBA先在DB_NAME对应的生产库启用配套扩展。")
        _stage = "initialization.base_migration_and_admin"
        await init_db(raise_on_error=True)
        _stage = "initialization.replay_v2_migration"
        await init_replay_v2_db(raise_on_error=True)
        _stage = "initialization.timescale_conversion"
        from app.core.timeseries import configure_timescale
        async with engine.begin() as connection:
            converted = await connection.run_sync(lambda bind: configure_timescale(bind, replay_v2=True))
        if not converted:
            print("DIAGNOSTIC [TIMESCALE_OPTIONAL] initialization: 普通PostgreSQL表模式；无Timescale压缩和自动保留策略。")
        _stage = "initialization.validate_versions"
        await validate_database()
        from app.core.database import async_session_maker
        from seed_sources import seed_sources
        _stage = "initialization.seed_sources"
        async with async_session_maker() as session:
            async with session.begin():
                report = await seed_sources(session, Path(__file__).with_name("test-sources.json"))
        print(f"Source configuration initialized: {report}")
        print("Canonical and Replay V2 migrations are current; administrator initialized")
    finally:
        await close_db()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        report = Report()
        report.error(_stage, exc)
        report.emit()
        sys.exit(1)
