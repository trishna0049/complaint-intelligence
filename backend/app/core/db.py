"""Async SQLAlchemy 2 engine and sessions (PostgreSQL via asyncpg)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

# Deterministic constraint names so Alembic migrations are stable.
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(
            s.database_url,
            pool_size=s.database_pool_size,
            max_overflow=s.database_pool_size,
            pool_pre_ping=True,
            connect_args={"server_settings": {"timezone": "UTC", "application_name": "complaint-intel"}},
        )
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


def SessionLocal() -> AsyncSession:
    return session_factory()()


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request."""
    async with SessionLocal() as session:
        yield session
