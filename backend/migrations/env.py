"""Alembic environment: async engine, URL from app settings (or `-x url=...`)."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app import models  # noqa: F401  (registers every table)
from app.core.config import get_settings
from app.core.db import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def database_url() -> str:
    return (
        context.get_x_argument(as_dictionary=True).get("url")
        or config.attributes.get("url")
        or (get_settings().database_url)
    )


def include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    # Indexes created with raw SQL in migrations (HNSW, GIN) are not modelled one-to-one; don't drop them.
    return not (type_ == "index" and reflected and compare_to is None)


def run_migrations_offline() -> None:
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, include_object=include_object, compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(database_url())
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
