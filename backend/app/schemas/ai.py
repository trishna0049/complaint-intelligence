from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

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


class AcceptDraftRequest(BaseModel):
    """The reply the agent approves — the AI draft as is, or their edited version."""

    response: str = Field(min_length=1, max_length=10_000)

    @field_validator("response")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("The reply can't be empty")
        return v.strip()


class DiscardDraftRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)
