"""Health and reference data."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.ai.classifier import get_classifier
from app.ai.priority import BASE_PRIORITY
from app.core.config import get_settings

router = APIRouter(tags=["meta"])


@router.get("/health")
def health() -> dict[str, Any]:
    s = get_settings()
    clf = get_classifier()
    return {
        "status": "ok",
        "classifier": clf.version if clf else None,
        "sentiment_model": s.sentiment_model if s.enable_transformers else "lexicon-fallback",
        "llm_provider": "openai" if s.llm_provider == "openai" and s.openai_api_key else "mock",
    }


@router.get("/categories")
def categories() -> list[dict[str, str]]:
    return [{"name": n, "base_priority": p} for n, p in BASE_PRIORITY.items()]
