"""Async SQLAlchemy engine + session factory for SQLite (aiosqlite).

Provides:
- `engine` — async engine bound to AIDAILY_DB_PATH (WAL enabled)
- `AsyncSessionLocal` — session factory
- `get_session()` — FastAPI dependency yielding an AsyncSession
- `init_db()` — create tables / set pragmas (used in tests + startup)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    AsyncSessionTransaction,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all ORM models."""


def _build_engine(db_path: str) -> AsyncEngine:
    """Construct an async engine for SQLite with WAL pragmas.

    Special case: `:memory:` returns an in-memory engine for tests.
    """
    if db_path == ":memory:":
        url = "sqlite+aiosqlite:///:memory:"
        # Static pool required so all sessions share one in-memory connection.
        return create_async_engine(
            url,
            echo=False,
            poolclass=_StaticPool,
            future=True,
        )

    # Ensure parent dir exists for file-based DBs.
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite+aiosqlite:///{db_path}"
    return create_async_engine(url, echo=False, future=True)


# Imported lazily to avoid hard dependency at module import time on Windows
# where poolclass resolution can be brittle. Done at module level for reuse.
try:
    from sqlalchemy.pool import StaticPool as _StaticPool
except ImportError:  # pragma: no cover
    _StaticPool = None  # type: ignore[assignment]


def make_engine(db_path: str | None = None) -> AsyncEngine:
    """Public factory: build engine from explicit path or settings."""
    path = db_path if db_path is not None else get_settings().db_path
    return _build_engine(path)


# Module-level default engine (lazily created so tests can override).
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine  # noqa: PLW0603
    if _engine is None:
        _engine = make_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory  # noqa: PLW0603
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _session_factory


def reset_engine_cache() -> None:
    """Test helper: drop cached engine/factory so next call rebuilds."""
    global _engine, _session_factory  # noqa: PLW0603
    if _engine is not None:
        # Best-effort cleanup; ignore errors in tests.
        try:
            import asyncio

            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Cannot await here; caller should dispose explicitly.
                pass
            else:
                loop.run_until_complete(_engine.dispose())
        except Exception:
            pass
    _engine = None
    _session_factory = None


async def init_db(engine: AsyncEngine | None = None) -> None:
    """Create all tables + apply WAL pragmas. Used by tests + startup."""
    from app import models  # noqa: F401 ensure models imported for metadata

    target = engine or get_engine()
    async with target.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.exec_driver_sql("PRAGMA synchronous=NORMAL")
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield an AsyncSession bound to current engine."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def current_session() -> AsyncSession:
    """Non-dependency helper for code paths without FastAPI DI."""
    factory = get_session_factory()
    return factory()


__all__ = [
    "AsyncSessionTransaction",
    "Base",
    "get_engine",
    "get_session",
    "get_session_factory",
    "init_db",
    "make_engine",
    "reset_engine_cache",
]
