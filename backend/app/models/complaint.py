from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, Sequence, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

# Human-readable reference numbers come from a sequence so concurrent inserts never collide.
REFERENCE_SEQ = Sequence("complaint_reference_seq", start=1, metadata=Base.metadata)


class Complaint(Base):
    __tablename__ = "complaints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference: Mapped[str] = mapped_column(
        String(16),
        unique=True,
        server_default=text("'CMP-' || lpad(nextval('complaint_reference_seq')::text, 6, '0')"),
    )
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- AI triage ---
    category: Mapped[str | None] = mapped_column(String(64), index=True)
    category_confidence: Mapped[float | None] = mapped_column(Float)
    intent: Mapped[str | None] = mapped_column(String(64))
    intent_confidence: Mapped[float | None] = mapped_column(Float)
    sentiment: Mapped[str | None] = mapped_column(String(16), index=True)
    sentiment_score: Mapped[float | None] = mapped_column(Float)  # 1 (very negative) .. 5 (very positive)
    priority: Mapped[str] = mapped_column(String(16), default="Medium", index=True)
    priority_reasons: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    entities: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    # "model" for live triage; "dataset" when labels come from the source data (imported history)
    labels_from: Mapped[str] = mapped_column(String(16), default="model")
    model_version: Mapped[str | None] = mapped_column(String(64))

    insights: Mapped[list[AIInsight]] = relationship(
        back_populates="complaint", cascade="all, delete-orphan", order_by="AIInsight.id.desc()", lazy="selectin"
    )

    __table_args__ = (Index("ix_complaints_created_category", "created_at", "category"),)


class AIInsight(Base):
    """LLM output for a complaint: summary, key issues and recommended actions."""

    __tablename__ = "ai_insights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    complaint_id: Mapped[int] = mapped_column(ForeignKey("complaints.id", ondelete="CASCADE"), index=True)
    summary: Mapped[str] = mapped_column(Text)
    key_issues: Mapped[list[str]] = mapped_column(JSONB)
    recommended_actions: Mapped[list[str]] = mapped_column(JSONB)
    customer_reply: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(16))
    # Token usage and estimated cost for real LLM calls (None for the mock provider).
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    complaint: Mapped[Complaint] = relationship(back_populates="insights")
