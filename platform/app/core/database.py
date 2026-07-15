"""road9 database bootstrap, migrations, and async session management."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import AsyncGenerator

import asyncpg
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


logger = logging.getLogger(__name__)


engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def _connection_kwargs(database: str) -> dict:
    return {
        "host": settings.db_host,
        "port": settings.db_port,
        "user": settings.db_user,
        "password": settings.db_password,
        "database": database,
        "timeout": 5,
    }


async def ensure_target_database() -> None:
    """Create road9 when local PostgreSQL is reachable and it is absent."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", settings.db_name):
        raise RuntimeError("DB_NAME contains unsupported characters")
    conn = await asyncpg.connect(**_connection_kwargs(settings.db_bootstrap_database))
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", settings.db_name)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{settings.db_name}"')
            logger.info("Created PostgreSQL database %s", settings.db_name)
    finally:
        await conn.close()


def _run_alembic_upgrade() -> None:
    platform_dir = Path(__file__).resolve().parents[2]
    config = Config(str(platform_dir / "alembic.ini"))
    config.set_main_option("script_location", str(platform_dir / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")


def _alembic_head() -> str:
    platform_dir = Path(__file__).resolve().parents[2]
    config = Config(str(platform_dir / "alembic.ini"))
    config.set_main_option("script_location", str(platform_dir / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise RuntimeError("Alembic migration head is missing")
    return head


async def database_revision() -> str | None:
    """Return the installed UAV migration revision without invoking Alembic."""
    conn = await asyncpg.connect(**_connection_kwargs(settings.db_name))
    try:
        exists = await conn.fetchval("SELECT to_regclass('public.uav_alembic_version')")
        if not exists:
            return None
        return await conn.fetchval("SELECT version_num FROM uav_alembic_version LIMIT 1")
    finally:
        await conn.close()


def _json_value(value) -> str:
    if value is None:
        return "[]"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


async def migrate_legacy_core_data() -> None:
    """Idempotently copy the small legacy users/alerts baseline into road9."""
    if settings.db_legacy_name == settings.db_name:
        return
    admin = await asyncpg.connect(**_connection_kwargs(settings.db_bootstrap_database))
    try:
        legacy_exists = await admin.fetchval(
            "SELECT 1 FROM pg_database WHERE datname=$1", settings.db_legacy_name
        )
    finally:
        await admin.close()
    if not legacy_exists:
        return

    legacy = await asyncpg.connect(**_connection_kwargs(settings.db_legacy_name))
    target = await asyncpg.connect(**_connection_kwargs(settings.db_name))
    try:
        table_names = {
            row["table_name"]
            for row in await legacy.fetch(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name IN ('users','alerts')"
            )
        }
        if "users" in table_names:
            for row in await legacy.fetch(
                "SELECT id,username,email,hashed_password,role,is_active,created_at,updated_at FROM users"
            ):
                await target.execute(
                    """INSERT INTO uav_users
                    (id,username,email,hashed_password,role,is_active,created_at,updated_at)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8)
                    ON CONFLICT (id) DO UPDATE SET
                      username=EXCLUDED.username,email=EXCLUDED.email,
                      hashed_password=EXCLUDED.hashed_password,role=EXCLUDED.role,
                      is_active=EXCLUDED.is_active""",
                    *row.values(),
                )
            await target.execute(
                "SELECT setval(pg_get_serial_sequence('uav_users','id'), "
                "GREATEST(COALESCE((SELECT max(id) FROM uav_users),1),1), true)"
            )
        if "alerts" in table_names:
            rows = await legacy.fetch(
                """SELECT id,intersection_id,alert_type,severity,title,description,status,
                timestamp,track_ids,snapshot_url,video_clip_url,vlm_summary,acknowledged_by,
                acknowledged_at,push_logs,updated_at FROM alerts"""
            )
            for row in rows:
                values = list(row.values())
                values[8] = _json_value(values[8])
                values[14] = _json_value(values[14])
                await target.execute(
                    """INSERT INTO uav_alerts
                    (id,intersection_id,alert_type,severity,title,description,status,timestamp,
                     track_ids,snapshot_url,video_clip_url,vlm_summary,acknowledged_by,
                     acknowledged_at,push_logs,updated_at)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::json,$10,$11,$12,$13,$14,$15::json,$16)
                    ON CONFLICT (id) DO NOTHING""",
                    *values,
                )
    finally:
        await legacy.close()
        await target.close()


async def init_db() -> bool:
    """Ensure road9 exists, migrate schema/data, and seed the local admin."""
    try:
        await ensure_target_database()
        installed_revision = await database_revision()
        migration_head = await asyncio.to_thread(_alembic_head)
        if installed_revision != migration_head:
            await asyncio.to_thread(_run_alembic_upgrade)
        else:
            logger.info("PostgreSQL schema already at Alembic head %s", migration_head)
        await migrate_legacy_core_data()

        from app.models.user import User
        from app.services.auth_service import get_password_hash

        async with async_session_maker() as session:
            result = await session.execute(select(User).where(User.username == "admin"))
            admin_user = result.scalar_one_or_none()
            if admin_user is None:
                session.add(
                    User(
                        username="admin",
                        email="admin@trafficanalyzer.dev",
                        hashed_password=get_password_hash("admin123"),
                        role="admin",
                        is_active=True,
                    )
                )
                await session.commit()
            elif admin_user.email == "admin@traffic.local":
                admin_user.email = "admin@trafficanalyzer.dev"
                await session.commit()
        return True
    except Exception as exc:
        logger.warning("Database initialization failed: %s", exc)
        return False


async def close_db() -> None:
    await engine.dispose()
