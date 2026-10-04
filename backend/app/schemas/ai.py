from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.tickets import TicketCreate


class AnalyzeRequest(TicketCreate):
    """Same fields as a new ticket; nothing is saved."""


class TriagePreview(BaseModel):
    category: str | None
    category_confidence: float | None
    top_categories: list[tuple[str, float]]
    intent: str | None
    intent_confidence: float | None
    sentiment: str
    sentiment_score: float
    priority: str
    priority_reasons: list[dict[str, str]]
    entities: dict[str, Any]
    needs_review: bool
    model_version: str


class DraftResponseRequest(BaseModel):
    ticket_id: int = Field(ge=1)
