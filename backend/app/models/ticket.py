from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, Sequence, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

# Ticket numbers (INC-00001 ... INC-123456) come from a sequence so concurrent inserts never collide. The SQL
# function next_ticket_number() (migration 0002) pads to at least five digits.
TICKET_NUMBER_SEQ = Sequence("ticket_number_seq", start=1, metadata=Base.metadata)
TICKET_NUMBER_DEFAULT = text("next_ticket_number()")


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_number: Mapped[str] = mapped_column(String(16), unique=True, server_default=TICKET_NUMBER_DEFAULT)
    external_id: Mapped[str | None] = mapped_column(String(64), unique=True)  # dataset "Unique id"
    source: Mapped[str] = mapped_column(String(16), default="new")  # "dataset" | "new"

    subject: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    # Where the description came from: "customer" (typed in the app), "dataset_remark" (survey remark) or
    # "template" (dataset row had no remark, so a templated sentence was generated — excluded from training).
    description_source: Mapped[str] = mapped_column(String(16), default="customer")
    channel: Mapped[str] = mapped_column(String(16), default="Web")
    customer_name: Mapped[str | None] = mapped_column(String(160))
    order_id: Mapped[str | None] = mapped_column(String(64))
    product: Mapped[str | None] = mapped_column(String(120))
    amount_inr: Mapped[float | None] = mapped_column(Float)
    city: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), default="Open", index=True)  # Open | In Progress | Resolved
    csat_score: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- current AI triage (each run is also stored in ai_analyses) ---
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
    # "model" for live triage; "dataset" when labels come from the source data (imported history); "human"
    labels_from: Mapped[str] = mapped_column(String(16), default="model")
    model_version: Mapped[str | None] = mapped_column(String(64))

    analyses: Mapped[list[AIAnalysis]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="AIAnalysis.id.desc()", lazy="selectin"
    )

    __table_args__ = (Index("ix_tickets_created_category", "created_at", "category"),)


class AIAnalysis(Base):
    """One AI run on a ticket. kind="triage": classification only; kind="copilot": the triage snapshot plus the
    LLM's summary, key issues, recommendations and draft response."""

    __tablename__ = "ai_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="copilot")
    # triage snapshot
    category: Mapped[str | None] = mapped_column(String(64))
    intent: Mapped[str | None] = mapped_column(String(64))
    sentiment: Mapped[str | None] = mapped_column(String(16))
    priority: Mapped[str | None] = mapped_column(String(16))
    entities: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    confidence: Mapped[float | None] = mapped_column(Float)
    # copilot output (None for kind="triage")
    summary: Mapped[str | None] = mapped_column(Text)
    key_issues: Mapped[list[str] | None] = mapped_column(JSONB)
    recommendations: Mapped[list[str] | None] = mapped_column(JSONB)
    draft_response: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(16))
    model: Mapped[str | None] = mapped_column(String(64))
    model_version: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(16))
    # Token usage and estimated cost for real LLM calls (None for the mock provider).
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket: Mapped[Ticket] = relationship(back_populates="analyses")
