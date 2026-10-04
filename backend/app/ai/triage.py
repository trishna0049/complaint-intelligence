"""Automated triage: category + intent (scikit-learn), sentiment (Hugging Face), entities (rules),
priority (business rules)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.ai.classifier import ComplaintClassifier, get_classifier
from app.ai.entities import extract_entities
from app.ai.priority import decide_priority
from app.ai.sentiment import load_sentiment
from app.core.config import get_settings


@dataclass
class TriageResult:
    category: str | None
    category_confidence: float | None
    intent: str | None
    intent_confidence: float | None
    sentiment: str
    sentiment_score: float
    priority: str
    priority_reasons: list[dict[str, str]]
    entities: dict[str, Any]
    needs_review: bool
    model_version: str
    top_categories: list[tuple[str, float]] = field(default_factory=list)


def triage(
    text: str,
    *,
    channel: str | None = None,
    product: str | None = None,
    amount_inr: float | None = None,
    order_id: str | None = None,
) -> TriageResult:
    entities = extract_entities(text)
    amount = amount_inr if amount_inr is not None else entities["max_amount_inr"]
    has_order = bool(order_id or entities["order_ids"])

    clf = get_classifier()
    category = intent = None
    cat_conf = int_conf = None
    top: list[tuple[str, float]] = []
    version = "rules-only (classifier not trained)"
    if clf is not None:
        cat, inte = clf.predict(ComplaintClassifier.frame(text, channel, product, amount, has_order))
        category, cat_conf, top = cat.label, cat.confidence, cat.top
        intent, int_conf = inte.label, inte.confidence
        version = clf.version

    sentiment_model = load_sentiment()
    s = sentiment_model.predict(text)
    decision = decide_priority(category, s.label, amount, entities["repeat_contact"], intent, text)
    return TriageResult(
        category=category,
        category_confidence=round(cat_conf, 4) if cat_conf is not None else None,
        intent=intent,
        intent_confidence=round(int_conf, 4) if int_conf is not None else None,
        sentiment=s.label,
        sentiment_score=s.score,
        priority=decision.priority,
        priority_reasons=[
            {
                "rule": "BASE",
                "reason": f"Base priority for {category or 'unknown category'}",
                "from": "",
                "to": decision.base,
            },
            *decision.reasons,
        ],
        entities=entities,
        needs_review=cat_conf is None or cat_conf < get_settings().review_threshold,
        model_version=f"{version} + {getattr(sentiment_model, 'name', 'sentiment')}",
        top_categories=top,
    )
