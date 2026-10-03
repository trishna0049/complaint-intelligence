from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Stored as naive UTC (SQLite has no time zones), always returned timezone-aware."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None else None


class Complaint(Base):
    __tablename__ = "complaints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # CMP-000123
    external_id: Mapped[str | None] = mapped_column(String(64), unique=True)  # dataset "Unique id"
    source: Mapped[str] = mapped_column(String(16), default="new")  # "dataset" | "new"

    subject: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    text_is_template: Mapped[bool] = mapped_column(Boolean, default=False)  # dataset row had no remark
    channel: Mapped[str] = mapped_column(String(16), default="Web")
    customer_name: Mapped[str | None] = mapped_column(String(160))
    order_id: Mapped[str | None] = mapped_column(String(64))
    product: Mapped[str | None] = mapped_column(String(120))
    amount_inr: Mapped[float | None] = mapped_column(Float)
    city: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), default="Open", index=True)  # Open | In Progress | Resolved
    csat_score: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    # --- AI triage ---
    category: Mapped[str | None] = mapped_column(String(64), index=True)
    category_confidence: Mapped[float | None] = mapped_column(Float)
    intent: Mapped[str | None] = mapped_column(String(64))
    intent_confidence: Mapped[float | None] = mapped_column(Float)
    sentiment: Mapped[str | None] = mapped_column(String(16), index=True)
    sentiment_score: Mapped[float | None] = mapped_column(Float)  # 1 (very negative) .. 5 (very positive)
    priority: Mapped[str] = mapped_column(String(16), default="Medium", index=True)
    priority_reasons: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    entities: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    # "model" for live triage; "dataset" when labels come from the source data (imported history)
    labels_from: Mapped[str] = mapped_column(String(16), default="model")
    model_version: Mapped[str | None] = mapped_column(String(64))

    insights: Mapped[list[AIInsight]] = relationship(
        back_populates="complaint", cascade="all, delete-orphan", order_by="AIInsight.id.desc()"
    )

    __table_args__ = (Index("ix_complaints_created_category", "created_at", "category"),)


class AIInsight(Base):
    """LLM output for a complaint: summary, key issues and recommended actions."""

    __tablename__ = "ai_insights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    complaint_id: Mapped[int] = mapped_column(ForeignKey("complaints.id", ondelete="CASCADE"), index=True)
    summary: Mapped[str] = mapped_column(Text)
    key_issues: Mapped[list[str]] = mapped_column(JSON)
    recommended_actions: Mapped[list[str]] = mapped_column(JSON)
    customer_reply: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    complaint: Mapped[Complaint] = relationship(back_populates="insights")
