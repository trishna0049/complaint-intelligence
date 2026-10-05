from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.lifecycle import Status
from app.schemas.tickets import UserRef

MatchedBy = Literal["meaning", "keywords", "both"]


def _strip(v: str | None) -> str | None:
    return v.strip() if isinstance(v, str) else v


class ArticleCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=20, max_length=20_000)
    category: str | None = Field(default=None, max_length=64, description="A ticket category, or empty = general")

    _clean = field_validator("title", "body", "category")(_strip)


class ArticleUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    body: str | None = Field(default=None, min_length=20, max_length=20_000)
    category: str | None = Field(default=None, max_length=64)

    _clean = field_validator("title", "body", "category")(_strip)


class ArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    body: str
    category: str | None
    usage_count: int
    updated_by: UserRef | None
    created_at: datetime
    updated_at: datetime


class ArticleSummary(BaseModel):
    id: int
    title: str
    category: str | None
    snippet: str
    usage_count: int
    updated_at: datetime


class ArticleHitOut(ArticleSummary):
    score: float
    similarity: float | None
    matched_by: MatchedBy


class SimilarTicketOut(BaseModel):
    id: int
    ticket_number: str
    subject: str
    snippet: str
    status: Status
    category: str | None
    intent: str | None
    priority: str | None
    resolution: str | None
    csat_score: int | None
    source: str
    created_at: datetime
    score: float
    similarity: float | None
    matched_by: MatchedBy
