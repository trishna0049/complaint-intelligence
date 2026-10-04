"""Create the database if it is missing, optionally wipe it, and apply all Alembic migrations.

Usage:  python -m scripts.prepare_db [--url URL] [--reset]

`--reset` drops and recreates the public schema first (used by the end-to-end test database).
"""

from __future__ import annotations

import argparse
import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import BACKEND_DIR, get_settings


async def ensure_database(url: str, reset: bool) -> None:
    target = make_url(url)
    admin = create_async_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        exists = await conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": target.database})
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{target.database}"'))
            print(f"created database {target.database}")
    await admin.dispose()
    if reset:
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        await engine.dispose()
        print(f"reset schema of {target.database}")


def migrate(url: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["url"] = url
    command.upgrade(cfg, "head")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=None, help="defaults to DATABASE_URL")
    parser.add_argument("--reset", action="store_true", help="drop and recreate the schema first")
    args = parser.parse_args()
    url = args.url or get_settings().database_url
    asyncio.run(ensure_database(url, args.reset))
    migrate(url)


if __name__ == "__main__":
    main()
