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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from alembic import command
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


async def init_db() -> bool:
    """Ensure road9 exists, migrate the schema, and seed the local admin."""
    try:
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
        logger.warning("Database initialization failed: %s", exc)
        return False


async def close_db() -> None:
    await engine.dispose()
