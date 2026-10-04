"""Test setup: a dedicated PostgreSQL database (TEST_DATABASE_URL, migrated with Alembic once per run and
truncated before every test), no transformer download (lexicon sentiment fallback), mock LLM, and a tiny
classifier trained on synthetic data so tests never depend on the dataset."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

from dotenv import dotenv_values

_ROOT = Path(__file__).resolve().parents[2]
_env = dotenv_values(_ROOT / ".env") if (_ROOT / ".env").is_file() else {}
TEST_DB = (
    os.environ.get("TEST_DATABASE_URL")
    or _env.get("TEST_DATABASE_URL")
    or ("postgresql+asyncpg://complaint:complaint_dev_pw@localhost:15432/complaints_test")
)
if not TEST_DB.rstrip("/").endswith("_test"):
    raise RuntimeError(f"Refusing to run tests against a non-test database: {TEST_DB}")
os.environ["DATABASE_URL"] = TEST_DB
os.environ["ENVIRONMENT"] = "test"
os.environ["ENABLE_TRANSFORMERS"] = "false"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["OPENAI_API_KEY"] = ""
os.environ.setdefault("REDIS_URL", (_env.get("REDIS_URL") or "redis://localhost:16379/0").rsplit("/", 1)[0] + "/15")

import httpx  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from sklearn.compose import ColumnTransformer  # noqa: E402
from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.pipeline import Pipeline  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

import app.models  # noqa: E402,F401  (registers every table for TRUNCATE)
from app.ai.classifier import ComplaintClassifier, set_classifier  # noqa: E402
from app.core.config import BACKEND_DIR, get_settings  # noqa: E402
from app.core.db import Base, SessionLocal, dispose_engine  # noqa: E402
from app.core.redis import close_redis, get_redis  # noqa: E402

get_settings.cache_clear()

SYNTHETIC = [
    ("payment failed money deducted", "Payments related", "Online Payment Issues"),
    ("charged twice on my card", "Payments related", "Online Payment Issues"),
    ("upi payment pending", "Payments related", "Payment related Queries"),
    ("refund not received yet", "Refund Related", "Refund Enquiry"),
    ("where is my refund", "Refund Related", "Refund Enquiry"),
    ("return pickup not done", "Returns", "Reverse Pickup Enquiry"),
    ("want to return damaged item", "Returns", "Return request"),
    ("order delayed not delivered", "Order Related", "Delayed"),
    ("track my order status", "Order Related", "Order status enquiry"),
    ("good service thank you", "Feedback", "UnProfessional Behaviour"),
]


def tiny_classifier() -> ComplaintClassifier:
    df = pd.DataFrame(SYNTHETIC * 3, columns=["text", "category", "intent"])
    for col, val in (("channel", "Web"), ("product", "Unknown"), ("price_bucket", "none"), ("has_order_id", "no")):
        df[col] = val

    def model() -> Pipeline:
        return Pipeline(
            [
                ("features", ColumnTransformer([("text", TfidfVectorizer(), "text")])),
                ("clf", LogisticRegression(max_iter=500, C=10)),
            ]
        )

    meta = {
        "version": "test-tiny",
        "category_keyword_prior": True,
        "intents_by_category": {c: sorted({i for _, cc, i in SYNTHETIC if cc == c}) for _, c, _ in SYNTHETIC},
    }
    return ComplaintClassifier(model().fit(df, df["category"]), model().fit(df, df["intent"]), meta)


def migrate_test_database() -> None:
    """Drop everything and run every Alembic migration, so the tests also prove the migrations work."""
    import asyncio

    from alembic import command
    from alembic.config import Config

    async def reset() -> None:
        engine = create_async_engine(TEST_DB)
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        await engine.dispose()

    asyncio.run(reset())
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["url"] = TEST_DB
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True, scope="session")
def _schema_and_models() -> Iterator[None]:
    migrate_test_database()
    set_classifier(tiny_classifier())
    yield
    set_classifier(None)


@pytest.fixture(autouse=True, scope="session")
async def _teardown_connections() -> AsyncIterator[None]:
    yield
    await dispose_engine()
    await close_redis()


TABLES = ", ".join(t.name for t in Base.metadata.sorted_tables)


@pytest.fixture(autouse=True)
async def _clean_db() -> AsyncIterator[None]:
    async with SessionLocal() as db:
        await db.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        for seq in Base.metadata._sequences.values():
            await db.execute(text(f"ALTER SEQUENCE {seq.name} RESTART WITH 1"))
        await db.commit()
    await get_redis().flushdb()
    yield


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
