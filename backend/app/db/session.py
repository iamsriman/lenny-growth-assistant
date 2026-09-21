from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.db.models import Base

log = logging.getLogger("app.db")

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _connect_args() -> dict:
    if settings.is_sqlite:
        return {}
    # Supabase's transaction pooler (port 6543) is pgbouncer; asyncpg's
    # prepared-statement cache breaks there, so we disable it.
    return {"statement_cache_size": 0, "prepared_statement_cache_size": 0}


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        kwargs: dict = {"echo": settings.db_echo, "pool_pre_ping": True}
        if settings.is_sqlite and ":memory:" in settings.database_url:
            # Every connection to ":memory:" gets its own database, so the test
            # suite must reuse a single connection.
            from sqlalchemy.pool import StaticPool

            kwargs["poolclass"] = StaticPool
            kwargs["connect_args"] = {"check_same_thread": False}
            kwargs.pop("pool_pre_ping", None)
        if not settings.is_sqlite:
            kwargs["pool_size"] = settings.db_pool_size
            kwargs["max_overflow"] = 5
            kwargs["connect_args"] = _connect_args()
        _engine = create_async_engine(settings.database_url, **kwargs)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
        log.info("database engine created", extra={"component": "db",
                                                   "dialect": _engine.url.get_backend_name()})
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def init_db() -> None:
    """Create tables if they are missing.

    Deliberately `create_all` rather than Alembic: the brief asks for a
    one-command start. See architecture.md for the migration path.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("schema ready", extra={"component": "db"})


async def dispose_db() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None


async def db_health() -> dict:
    try:
        async with get_sessionmaker()() as s:
            await s.execute(text("SELECT 1"))
        return {"status": "ok", "dialect": get_engine().url.get_backend_name()}
    except Exception as exc:  # noqa: BLE001 - health must never raise
        log.warning("database health check failed", extra={"component": "db", "error": str(exc)})
        return {"status": "down", "error": str(exc)[:300]}


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def db_scope() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
