"""Test setup: a dedicated PostgreSQL database (TEST_DATABASE_URL, migrated with Alembic once per run and
truncated before every test), no transformer download (lexicon sentiment fallback), mock LLM, and a tiny
classifier trained on synthetic data so tests never depend on the dataset."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
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
# Events run in-process right after each commit (same consumers, idempotency, retries and DLQ as with Kafka);
# the Kafka path itself is covered by test_kafka_integration.py.
os.environ["EVENTS_MODE"] = "inline"
os.environ["EVENT_RETRY_BACKOFF_SECONDS"] = "0"
os.environ["COPILOT_AUTO"] = "false"  # tests that want the LLM worker's auto-draft switch it on
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
from app.auth.security import create_access_token, hash_password  # noqa: E402
from app.core.config import BACKEND_DIR, get_settings  # noqa: E402
from app.core.db import Base, SessionLocal, dispose_engine  # noqa: E402
from app.core.redis import close_redis, get_redis  # noqa: E402
from app.models import Category, Department, SlaPolicy, Team, User  # noqa: E402
from app.services.sla_policies import DEFAULT_POLICIES  # noqa: E402
from scripts import seed as seed_script  # noqa: E402

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
PASSWORD = "Correct-Horse-42"
_PASSWORD_HASH = hash_password(PASSWORD)  # argon2 is slow on purpose; hash once per run


@dataclass
class Org:
    admin: User
    agent: User  # Payments Support
    other_agent: User  # Returns & Pickups
    teams: dict[str, Team]


async def seed_org() -> Org:
    """The 12 category teams (as scripts/seed.py), one admin and two agents in different teams."""
    async with SessionLocal() as db:
        depts = {name: Department(name=name) for name in seed_script.DEPARTMENTS}
        db.add_all(depts.values())
        await db.flush()
        teams: dict[str, Team] = {}
        for cat, (team, dept, desc) in seed_script.CATEGORY_TEAMS.items():
            teams[team] = Team(name=team, department_id=depts[dept].id)
            db.add(teams[team])
            await db.flush()
            db.add(Category(name=cat, description=desc, team_id=teams[team].id))
        admin = User(name="Ada Admin", email="admin@test.example", password_hash=_PASSWORD_HASH, role="ADMIN")
        agent = User(
            name="Arjun Agent",
            email="agent@test.example",
            password_hash=_PASSWORD_HASH,
            role="AGENT",
            team_id=teams["Payments Support"].id,
        )
        other = User(
            name="Olga Other",
            email="other@test.example",
            password_hash=_PASSWORD_HASH,
            role="AGENT",
            team_id=teams["Returns & Pickups"].id,
        )
        db.add_all([admin, agent, other])
        db.add_all(SlaPolicy(name=n, priority=p, target_minutes=m) for n, p, m in DEFAULT_POLICIES)
        await db.commit()
        return Org(admin, agent, other, teams)


@pytest.fixture(autouse=True)
async def org() -> AsyncIterator[Org]:
    async with SessionLocal() as db:
        await db.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        for seq in Base.metadata._sequences.values():
            await db.execute(text(f"ALTER SEQUENCE {seq.name} RESTART WITH 1"))
        await db.commit()
    await get_redis().flushdb()
    yield await seed_org()


def auth_headers(user: User) -> dict[str, str]:
    token, _ = create_access_token(user.id, user.role)
    return {"Authorization": f"Bearer {token}"}


def _client(headers: dict[str, str] | None = None) -> httpx.AsyncClient:
    from app.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=headers)


@pytest.fixture
async def anon() -> AsyncIterator[httpx.AsyncClient]:
    """No credentials."""
    async with _client() as c:
        yield c


@pytest.fixture
async def client(org: Org) -> AsyncIterator[httpx.AsyncClient]:
    """Signed in as the admin (can do everything)."""
    async with _client(auth_headers(org.admin)) as c:
        yield c


@pytest.fixture
async def agent_client(org: Org) -> AsyncIterator[httpx.AsyncClient]:
    """Signed in as an agent in Payments Support."""
    async with _client(auth_headers(org.agent)) as c:
        yield c


@pytest.fixture
async def other_agent_client(org: Org) -> AsyncIterator[httpx.AsyncClient]:
    """Signed in as an agent in Returns & Pickups."""
    async with _client(auth_headers(org.other_agent)) as c:
        yield c
