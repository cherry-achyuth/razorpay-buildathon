"""Async database engine, session factory, and connectivity checking."""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.core.logging import logger

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Returns or initializes the global AsyncEngine instance."""
    global _engine
    if _engine is None:
        settings = get_settings()
        connect_args: dict[str, Any] = {}
        # If using SQLite in tests, enable check_same_thread=False
        if settings.async_database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        elif "+asyncpg" in settings.async_database_url:
            connect_args["timeout"] = 2.0
            connect_args["command_timeout"] = 2.0

        _engine = create_async_engine(
            settings.async_database_url,
            echo=settings.DEBUG,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Returns or initializes the global async session factory."""
    global _session_factory
    if _session_factory is None:
        engine = get_engine()
        _session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def close_db_engine() -> None:
    """Disposes the database engine pool on application shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        logger.info("Closing database connection pool...")
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database connection pool closed.")


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for obtaining an isolated async database session."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def _probe_db(engine: AsyncEngine) -> bool:
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        scalar = result.scalar()
        return scalar == 1


async def check_db_connectivity() -> bool:
    """Executes a lightweight query to verify database reachability."""
    try:
        engine = get_engine()
        return await asyncio.wait_for(_probe_db(engine), timeout=2.0)
    except Exception as exc:
        logger.warning("Database connectivity check failed (unreachable): %s", exc)
        return False
