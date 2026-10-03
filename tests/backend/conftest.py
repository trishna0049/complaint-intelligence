"""Test setup: temporary SQLite DB, no transformer download (lexicon sentiment fallback), mock LLM,
and a tiny classifier trained on synthetic data so tests never depend on the dataset."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="complaint-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["ENABLE_TRANSFORMERS"] = "false"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["OPENAI_API_KEY"] = ""

import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sklearn.compose import ColumnTransformer  # noqa: E402
from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.pipeline import Pipeline  # noqa: E402

from app.ai.classifier import ComplaintClassifier, set_classifier  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import Base, get_engine, reset_engine  # noqa: E402
from app.services.dashboard import invalidate_cache  # noqa: E402

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


@pytest.fixture(autouse=True, scope="session")
def _models() -> Iterator[None]:
    set_classifier(tiny_classifier())
    yield
    set_classifier(None)


@pytest.fixture(autouse=True)
def _clean_db() -> Iterator[None]:
    invalidate_cache()
    reset_engine()
    Base.metadata.drop_all(get_engine())
    Base.metadata.create_all(get_engine())
    yield


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as c:
        yield c
