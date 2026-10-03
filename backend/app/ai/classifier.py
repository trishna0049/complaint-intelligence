"""Category and intent classifiers (scikit-learn pipelines trained by ml/train_classifiers.py)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import joblib
import numpy as np
import pandas as pd

from app.ai.keywords import blend_with_prior
from app.config import get_settings

log = logging.getLogger(__name__)


@dataclass
class Prediction:
    label: str
    confidence: float
    top: list[tuple[str, float]]


class ComplaintClassifier:
    """Wraps the saved pipelines. Input is a one-row frame with the same columns used in training."""

    def __init__(self, category_model: Any, intent_model: Any, meta: dict[str, Any]) -> None:
        self.category_model = category_model
        self.intent_model = intent_model
        self.meta = meta
        self.version = meta.get("version", "triage-v1")
        # Intents observed under each category, so the intent always agrees with the category.
        self.intents_by_category: dict[str, list[str]] = meta.get("intents_by_category", {})

    @staticmethod
    def frame(
        text: str, channel: str | None, product: str | None, amount_inr: float | None, has_order_id: bool
    ) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "text": text or "",
                    "channel": channel or "Unknown",
                    "product": product or "Unknown",
                    "price_bucket": price_bucket(amount_inr),
                    "has_order_id": "yes" if has_order_id else "no",
                }
            ]
        )

    def predict(self, X: pd.DataFrame) -> tuple[Prediction, Prediction]:
        text = X["text"].tolist()
        cat_classes = list(self.category_model.classes_)
        p_cat = self.category_model.predict_proba(X)
        if self.meta.get("category_keyword_prior", True):
            p_cat = blend_with_prior(text, p_cat, cat_classes)
        category = _top(p_cat[0], cat_classes)

        intent_classes = list(self.intent_model.classes_)
        p_int = self.intent_model.predict_proba(X)[0].copy()
        allowed = set(self.intents_by_category.get(category.label, []))
        if allowed:
            mask = np.array([c in allowed for c in intent_classes])
            if p_int[mask].sum() > 0:
                p_int = np.where(mask, p_int, 0.0)
                p_int = p_int / p_int.sum()
        intent = _top(p_int, intent_classes)
        return category, intent


def _top(p: np.ndarray, classes: list[str], k: int = 3) -> Prediction:
    order = np.argsort(p)[::-1][:k]
    return Prediction(classes[order[0]], float(p[order[0]]), [(classes[i], round(float(p[i]), 4)) for i in order])


def price_bucket(amount: float | None) -> str:
    if amount is None or amount != amount:  # None or NaN
        return "none"
    for limit, label in ((500, "<500"), (2000, "500-2k"), (10000, "2k-10k"), (50000, "10k-50k")):
        if amount < limit:
            return label
    return "50k+"


_override: ComplaintClassifier | None = None


def set_classifier(model: ComplaintClassifier | None) -> None:
    """Use a specific classifier instead of the saved artifacts (tests)."""
    global _override
    _override = model


def get_classifier() -> ComplaintClassifier | None:
    return _override if _override is not None else load_classifier()


@lru_cache
def load_classifier() -> ComplaintClassifier | None:
    d = get_settings().artifacts_dir
    try:
        meta = json.loads((d / "classifier_meta.json").read_text(encoding="utf-8"))
        model = ComplaintClassifier(
            joblib.load(d / "category_model.joblib"), joblib.load(d / "intent_model.joblib"), meta
        )
        log.info("loaded classifier %s", model.version)
        return model
    except FileNotFoundError:
        log.warning("classifier artifacts not found in %s - run ml/train_classifiers.py", d)
        return None
