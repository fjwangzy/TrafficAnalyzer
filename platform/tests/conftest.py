"""Shared test isolation for explicitly enabled PostgreSQL integrations."""

import os

import pytest_asyncio

from app.core.database import engine


@pytest_asyncio.fixture(autouse=True)
async def isolate_postgres_async_pool():
    """Dispose pooled asyncpg connections on the event loop that created them."""
    yield
    if os.environ.get("RUN_PG_INTEGRATION") == "1":
        await engine.dispose()
