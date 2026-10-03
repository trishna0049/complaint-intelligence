from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _session_factory
    if _engine is None:
        url = get_settings().database_url
        if url.startswith("sqlite:///"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
        if url.startswith("sqlite"):

            @event.listens_for(_engine, "connect")
            def _pragmas(conn, _record):  # type: ignore[no-untyped-def]
                cur = conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()

        _session_factory = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def init_db() -> None:
    from app import models  # noqa: F401  (register tables)

    Base.metadata.create_all(get_engine())


def reset_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def SessionLocal() -> Session:
    get_engine()
    assert _session_factory is not None
    return _session_factory()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
