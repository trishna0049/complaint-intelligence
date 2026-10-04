from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Status = Literal["Open", "In Progress", "Resolved"]
Channel = Literal["Web", "Email", "Inbound", "Outcall"]


class TicketCreate(BaseModel):
    subject: str | None = Field(default=None, max_length=255)
    description: str = Field(min_length=5, max_length=10_000)
    channel: Channel = "Web"
    customer_name: str | None = Field(default=None, max_length=160)
    order_id: str | None = Field(default=None, max_length=64)
    product: str | None = Field(default=None, max_length=120)
    amount_inr: float | None = Field(default=None, ge=0, le=100_000_000)
    city: str | None = Field(default=None, max_length=120)

    @field_validator("description")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if len(v.strip()) < 5:
            raise ValueError("Describe the complaint (at least 5 characters)")
        return v.strip()


class TicketUpdate(BaseModel):
    status: Status | None = None
    category: str | None = Field(default=None, max_length=64)  # human correction


class TicketListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_number: str
    subject: str
    channel: str
    status: str
    category: str | None
    intent: str | None
    sentiment: str | None
    priority: str
    category_confidence: float | None
    needs_review: bool
    source: str
    description_source: str
    customer_name: str | None
    city: str | None
    created_at: datetime


class AnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    category: str | None
    intent: str | None
    sentiment: str | None
    priority: str | None
    confidence: float | None
    summary: str | None
    key_issues: list[str] | None
    recommendations: list[str] | None
    draft_response: str | None
    provider: str | None
    model: str | None
    model_version: str | None
    prompt_version: str | None
    usage: dict[str, Any] | None = None
    created_at: datetime


class TicketDetail(TicketListItem):
    description: str
    order_id: str | None
    product: str | None
    amount_inr: float | None
    csat_score: int | None
    updated_at: datetime
    first_response_at: datetime | None
    resolved_at: datetime | None
    intent_confidence: float | None
    sentiment_score: float | None
    priority_reasons: list[dict[str, Any]] | None
    entities: dict[str, Any] | None
    labels_from: str
    model_version: str | None
    # Latest copilot output (summary, key issues, recommendations, draft response), if any.
    copilot: AnalysisOut | None = None
