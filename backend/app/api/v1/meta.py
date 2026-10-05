"""Health check (public: used by Docker and load balancers)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.ai.classifier import get_classifier
from app.ai.embeddings import get_embedder
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
        "embedding_model": get_embedder().name,
        "llm_provider": "openai" if s.llm_provider == "openai" and s.openai_api_key else "mock",
    }
