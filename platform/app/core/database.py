"""Database connection and session management."""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import select
from typing import AsyncGenerator

from app.core.config import settings


# Create async engine
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# Create async session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting database sessions."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Initialize database tables."""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        from app.models.user import User
        from app.services.auth_service import get_password_hash

        # Docker 和本地首次启动都需要可验证的默认账号；已有 admin 时保持原数据不变。
        async with async_session_maker() as session:
            result = await session.execute(select(User).where(User.username == "admin"))
            admin_user = result.scalar_one_or_none()
            if admin_user is None:
                session.add(User(
                    username="admin",
                    email="admin@trafficanalyzer.dev",
                    hashed_password=get_password_hash("admin123"),
                    role="admin",
                    is_active=True,
                ))
                await session.commit()
            elif admin_user.email == "admin@traffic.local":
                admin_user.email = "admin@trafficanalyzer.dev"
                await session.commit()
    except Exception as e:
        # Log but don't fail - database might not be available in dev
        import logging
        logging.getLogger(__name__).warning(f"Database initialization failed: {e}")


async def close_db():
    """Close database connections."""
    await engine.dispose()
