from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Status = Literal["Open", "In Progress", "Resolved"]


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


class ComplaintCreate(BaseModel):
    subject: str | None = Field(default=None, max_length=255)
    text: str = Field(min_length=5, max_length=10_000)
    channel: Literal["Web", "Email", "Inbound", "Outcall"] = "Web"
    customer_name: str | None = Field(default=None, max_length=160)
    order_id: str | None = Field(default=None, max_length=64)
    product: str | None = Field(default=None, max_length=120)
    amount_inr: float | None = Field(default=None, ge=0, le=100_000_000)
    city: str | None = Field(default=None, max_length=120)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if len(v.strip()) < 5:
            raise ValueError("Describe the complaint (at least 5 characters)")
        return v.strip()


class ComplaintUpdate(BaseModel):
    status: Status | None = None
    category: str | None = Field(default=None, max_length=64)  # human correction


class ComplaintListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reference: str
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
    text_is_template: bool
    customer_name: str | None
    city: str | None
    created_at: datetime


class InsightOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    summary: str
    key_issues: list[str]
    recommended_actions: list[str]
    customer_reply: str
    provider: str
    model: str
    prompt_version: str
    created_at: datetime


class ComplaintDetail(ComplaintListItem):
    text: str
    order_id: str | None
    product: str | None
    amount_inr: float | None
    csat_score: int | None
    resolved_at: datetime | None
    intent_confidence: float | None
    sentiment_score: float | None
    priority_reasons: list[dict[str, Any]] | None
    entities: dict[str, Any] | None
    labels_from: str
    model_version: str | None
    insight: InsightOut | None = None


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
