"""road9 database bootstrap, migrations, and async session management."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncGenerator
from pathlib import Path

import asyncpg
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from alembic import command
from app.core.config import settings

logger = logging.getLogger(__name__)


engine = create_async_engine(
    settings.database_url,
    connect_args=settings.database_connect_args,
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
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def _alembic_head() -> str:
    platform_dir = Path(__file__).resolve().parents[2]
    config = Config(str(platform_dir / "alembic.ini"))
    config.set_main_option("script_location", str(platform_dir / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise RuntimeError("Alembic migration head is missing")
    return head


def _replay_v2_alembic_config() -> Config:
    platform_dir = Path(__file__).resolve().parents[2]
    config = Config(str(platform_dir / "alembic_replay_v2.ini"))
    config.set_main_option("script_location", str(platform_dir / "alembic_replay_v2"))
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    return config


def _replay_v2_alembic_head() -> str:
    head = ScriptDirectory.from_config(_replay_v2_alembic_config()).get_current_head()
    if head is None:
        raise RuntimeError("Replay-v2 Alembic migration head is missing")
    return head


def _run_replay_v2_alembic_upgrade() -> None:
    command.upgrade(_replay_v2_alembic_config(), "head")


async def _installed_revision(table: str) -> str | None:
    async with engine.connect() as connection:
        exists = await connection.scalar(
            text("SELECT to_regclass(:table)"),
            {"table": f"{settings.db_schema}.{table}"},
        )
        if not exists:
            return None
        return await connection.scalar(text(
            f'SELECT version_num FROM "{settings.db_schema}"."{table}" LIMIT 1'
        ))


async def database_revision() -> str | None:
    return await _installed_revision("uav_alembic_version")


async def replay_v2_database_revision() -> str | None:
    return await _installed_revision("uav_replay_v2_alembic_version")


async def validate_database() -> bool:
    """Production startup checks only; deployment runs migrations explicitly."""
    if await database_revision() != await asyncio.to_thread(_alembic_head):
        raise RuntimeError("Database migrations are not current; run deploy init-db")
    if await replay_v2_database_revision() != await asyncio.to_thread(_replay_v2_alembic_head):
        raise RuntimeError("Fixed-Topic receipt/replay migrations are not current; run deploy init-db")
    async with engine.connect() as connection:
        actual = (await connection.execute(text("SELECT current_database(), current_schema()"))).one()
        if tuple(actual) != (settings.db_name, settings.db_schema):
            raise RuntimeError("Database/schema is missing, unexpected or not accessible")
        enabled = await connection.scalar(text(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='timescaledb')"
        ))
        if not enabled:
            if settings.db_timescale_required:
                raise RuntimeError("DBA must enable TimescaleDB before deployment")
            logger.warning("TimescaleDB unavailable: ordinary PostgreSQL tables; no compression/retention policies")
            return True
        hypertables = set((await connection.execute(text(
            "SELECT hypertable_name FROM timescaledb_information.hypertables "
            "WHERE hypertable_schema=current_schema()"
        ))).scalars())
        required = {"uav_traffic_metrics", "uav_system_metrics", "uav_telemetry_metrics",
                    "uav_track_points", "uav_conflict_events"}
        if settings.app_runtime_profile == "replay_v2":
            required.add("uav_replay_v2_traffic_metric_samples")
        if not required.issubset(hypertables):
            raise RuntimeError("Expected TimescaleDB hypertables are missing from the application schema")
    return True


async def init_replay_v2_db(*, raise_on_error: bool = False) -> bool:
    """Migrate only replay-v2 tables after asserting canonical road9 is current."""
    try:
        if not settings.db_auto_migrate:
            return await validate_database()
        installed_canonical = await database_revision()
        canonical_head = await asyncio.to_thread(_alembic_head)
        if installed_canonical != canonical_head:
            raise RuntimeError(
                "canonical road9 schema must already be at head; replay_v2 will not upgrade it"
            )
        installed_replay = await replay_v2_database_revision()
        replay_head = await asyncio.to_thread(_replay_v2_alembic_head)
        if installed_replay != replay_head:
            await asyncio.to_thread(_run_replay_v2_alembic_upgrade)
        else:
            logger.info("Replay-v2 schema already at Alembic head %s", replay_head)
        return True
    except Exception as exc:
        if raise_on_error:
            raise
        logger.warning("Replay-v2 database initialization failed: %s", exc)
        return False


async def init_db(*, raise_on_error: bool = False) -> bool:
    """Ensure road9 exists, migrate the schema, and seed the local admin."""
    try:
        if not settings.db_auto_migrate:
            return await validate_database()
        if settings.deployment_mode == "local":
            await ensure_target_database()
        installed_revision = await database_revision()
        migration_head = await asyncio.to_thread(_alembic_head)
        if installed_revision != migration_head:
            await asyncio.to_thread(_run_alembic_upgrade)
        else:
            logger.info("PostgreSQL schema already at Alembic head %s", migration_head)
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
                        hashed_password=get_password_hash(settings.bootstrap_admin_password),
                        role="admin",
                        is_active=True,
                    )
                )
                await session.commit()
        return True
    except Exception as exc:
        if raise_on_error:
            raise
        logger.warning("Database initialization failed: %s", exc)
        return False


async def close_db() -> None:
    await engine.dispose()
