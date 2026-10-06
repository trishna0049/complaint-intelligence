from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Sequence,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.org import Team, User
from app.models.sla import SlaPolicy

# Ticket numbers (INC-00001 ... INC-123456) come from a sequence so concurrent inserts never collide. The SQL
# function next_ticket_number() (migration 0002) pads to at least five digits.
TICKET_NUMBER_SEQ = Sequence("ticket_number_seq", start=1, metadata=Base.metadata)
TICKET_NUMBER_DEFAULT = text("next_ticket_number()")
CUSTOMER_CODE_SEQ = Sequence("customer_code_seq", start=1, metadata=Base.metadata)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_code: Mapped[str] = mapped_column(
        String(16), unique=True, server_default=text("'CUS-' || lpad(nextval('customer_code_seq')::text, 5, '0')")
    )
    name: Mapped[str] = mapped_column(String(160))
    segment: Mapped[str] = mapped_column(String(32), default="Standard")  # Standard | Premium
    region: Mapped[str | None] = mapped_column(String(32))  # North | South | East | West | Central
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_number: Mapped[str] = mapped_column(String(16), unique=True, server_default=TICKET_NUMBER_DEFAULT)
    external_id: Mapped[str | None] = mapped_column(String(64), unique=True)  # dataset "Unique id"
    source: Mapped[str] = mapped_column(String(16), default="new")  # "dataset" | "new"
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"), index=True)

    subject: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    # Keyword half of the hybrid similar-ticket search (the vector half is ticket_embeddings).
    description_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', coalesce(description, ''))", persisted=True)
    )
    # Where the description came from: "customer" (typed in the app), "dataset_remark" (survey remark) or
    # "template" (dataset row had no remark, so a templated sentence was generated — excluded from training).
    description_source: Mapped[str] = mapped_column(String(16), default="customer")
    channel: Mapped[str] = mapped_column(String(16), default="Web")
    customer_name: Mapped[str | None] = mapped_column(String(160))
    order_id: Mapped[str | None] = mapped_column(String(64))
    product: Mapped[str | None] = mapped_column(String(120))
    amount_inr: Mapped[float | None] = mapped_column(Float)
    city: Mapped[str | None] = mapped_column(String(120))
    # Lifecycle state — see app/domain/lifecycle.py for the only allowed moves.
    status: Mapped[str] = mapped_column(String(16), default="NEW", index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"))
    csat_score: Mapped[int | None] = mapped_column(Integer)
    resolution: Mapped[str | None] = mapped_column(Text)
    reopen_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # --- SLA clock (app/domain/sla.py; driven by the SLA worker) ---
    sla_policy_id: Mapped[int | None] = mapped_column(ForeignKey("sla_policies.id", ondelete="SET NULL"))
    sla_target_seconds: Mapped[int | None] = mapped_column(Integer)
    sla_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # moves out while paused
    sla_paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # a pause in progress
    sla_paused_seconds: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sla_stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_warned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_breached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # none | running | paused | met | breached  (at_risk is computed for display from the clock)
    sla_status: Mapped[str] = mapped_column(String(12), default="none", server_default="none")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id], lazy="joined")
    team: Mapped[Team | None] = relationship(lazy="joined")
    customer: Mapped[Customer | None] = relationship(lazy="joined")
    sla_policy: Mapped[SlaPolicy | None] = relationship(lazy="joined")
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id], lazy="noload")

    @property
    def top_categories(self) -> list[list[Any]]:
        """The latest triage run's alternatives (review queue / category correction)."""
        latest = next((a for a in self.analyses if a.kind == "triage"), None)
        return (latest.alternatives or []) if latest else []

    __table_args__ = (
        Index("ix_tickets_created_category", "created_at", "category"),
        Index("ix_tickets_assignee_status", "assignee_id", "status"),
        Index("ix_tickets_team_status", "team_id", "status"),
        Index("ix_tickets_created_by_id", "created_by_id"),
        Index("ix_tickets_description_tsv", "description_tsv", postgresql_using="gin"),
        Index("ix_tickets_sla_due", "sla_deadline", postgresql_where=text("sla_status = 'running'")),
        Index("ix_tickets_sla_status", "sla_status"),
        Index(
            "ix_tickets_review_queue",
            "created_at",
            postgresql_where=text(
                "needs_review AND status IN "
                "('NEW', 'TRIAGED', 'ASSIGNED', 'IN_PROGRESS', 'WAITING_CUSTOMER', 'ESCALATED')"
            ),
        ),
    )


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
    # The classifier's top categories with their probabilities, e.g. [["Refund Related", 0.41], ["Returns", 0.32]].
    alternatives: Mapped[list[list[Any]] | None] = mapped_column(JSONB)
    # copilot output (None for kind="triage")
    summary: Mapped[str | None] = mapped_column(Text)
    root_cause: Mapped[str | None] = mapped_column(Text)  # the model's hypothesis, shown as "likely root cause"
    key_issues: Mapped[list[str] | None] = mapped_column(JSONB)
    recommendations: Mapped[list[str] | None] = mapped_column(JSONB)
    draft_response: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(16))
    model: Mapped[str | None] = mapped_column(String(64))
    model_version: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(16))
    # Token usage and estimated cost for real LLM calls (None for the mock provider).
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    # RAG: the past tickets and help articles given to the copilot, and which of them it cited.
    grounding: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    # Human review of the draft reply (copilot only): pending -> accepted | discarded, or superseded by a newer run.
    # The AI never sends anything: "accepted" means an agent posted the (possibly edited) text as a comment.
    draft_status: Mapped[str | None] = mapped_column(String(12))
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    final_response: Mapped[str | None] = mapped_column(Text)  # what the agent actually posted
    edited: Mapped[bool | None] = mapped_column(Boolean)
    comment_id: Mapped[int | None] = mapped_column(ForeignKey("ticket_comments.id", ondelete="SET NULL"))
    discard_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket: Mapped[Ticket] = relationship(back_populates="analyses")
    reviewed_by: Mapped[User | None] = relationship(lazy="joined")


class TicketComment(Base):
    __tablename__ = "ticket_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)
    # True when the text came from the AI copilot's draft and an agent accepted it (never sent by the AI itself).
    ai_assisted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    author: Mapped[User | None] = relationship(lazy="joined")


class TicketEvent(Base):
    """The ticket timeline: one row for every change, written in the same transaction as the change."""

    __tablename__ = "ticket_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(48))  # created, triaged, assigned, status_changed, ...
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))  # None = system
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    actor: Mapped[User | None] = relationship(lazy="joined")

    __table_args__ = (Index("ix_ticket_events_ticket_created", "ticket_id", "created_at"),)


class TicketAttachment(Base):
    __tablename__ = "ticket_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    filename: Mapped[str] = mapped_column(String(255))  # sanitised original name, shown to users
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(80), unique=True)  # random name on disk, never user input
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    uploaded_by: Mapped[User | None] = relationship(lazy="joined")
