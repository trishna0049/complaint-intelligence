"""5-level sentiment with a pretrained Hugging Face model (1–5 star review model).

Stars map to: 1 Very Negative, 2 Negative, 3 Neutral, 4 Positive, 5 Very Positive.
Validated against the dataset's CSAT scores in ml/eval_sentiment.py.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.core.config import get_settings

log = logging.getLogger(__name__)

LABELS = ["Very Negative", "Negative", "Neutral", "Positive", "Very Positive"]


@dataclass
class SentimentResult:
    label: str
    score: float  # expected star rating, 1..5
    confidence: float


class TransformerSentiment:
    def __init__(self, model_name: str) -> None:
        os.environ.setdefault("HF_HOME", str(get_settings().hf_home))
        from transformers import pipeline

        self.name = model_name
        self.pipe = pipeline("text-classification", model=model_name, top_k=None, truncation=True, max_length=256)

    def predict_many(self, texts: list[str], batch_size: int = 64) -> list[SentimentResult]:
        out: list[SentimentResult] = []
        for scores in self.pipe([t or "." for t in texts], batch_size=batch_size):
            probs = [0.0] * 5
            for s in scores:
                stars = int(str(s["label"]).split()[0])  # "4 stars" -> 4
                probs[stars - 1] = float(s["score"])
            best = max(range(5), key=lambda i: probs[i])
            expected = sum((i + 1) * p for i, p in enumerate(probs))
            out.append(SentimentResult(LABELS[best], round(expected, 3), round(probs[best], 4)))
        return out

    def predict(self, text: str) -> SentimentResult:
        return self.predict_many([text])[0]


class LexiconSentiment:
    """Tiny fallback used in unit tests (ENABLE_TRANSFORMERS=false) — not used in production."""

    name = "lexicon-fallback"
    NEG = re.compile(r"\b(worst|pathetic|terrible|horrible|frustrat\w*|angry|fraud|cheat\w*|never|useless)\b", re.I)
    MILD_NEG = re.compile(r"\b(not|no|bad|poor|late|delay\w*|issue|problem|disappoint\w*)\b", re.I)
    POS = re.compile(r"\b(good|great|thanks?|thank you|happy|excellent|nice|helpful)\b", re.I)

    def predict(self, text: str) -> SentimentResult:
        neg, mild, pos = len(self.NEG.findall(text)), len(self.MILD_NEG.findall(text)), len(self.POS.findall(text))
        score = 3 + min(pos, 2) - min(mild, 1) - 2 * min(neg, 1)
        score = max(1, min(5, score))
        return SentimentResult(LABELS[score - 1], float(score), 0.5)

    def predict_many(self, texts: list[str], batch_size: int = 64) -> list[SentimentResult]:
        return [self.predict(t) for t in texts]


@lru_cache
def load_sentiment() -> Any:
    settings = get_settings()
    if not settings.enable_transformers:
        return LexiconSentiment()
    log.info("loading sentiment model %s", settings.sentiment_model)
    return TransformerSentiment(settings.sentiment_model)
