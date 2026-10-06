"""SLA policies (Admin-managed targets) and the SLA event log (spec: sla_policies, sla_events)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SlaPolicy(Base):
    """Resolution target for a priority, optionally narrowed to one category (the more specific policy wins)."""

    __tablename__ = "sla_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    priority: Mapped[str] = mapped_column(String(16))  # Low | Medium | High | Critical
    category: Mapped[str | None] = mapped_column(String(64))  # None = every category
    target_minutes: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("uq_sla_policies_priority_category", "priority", text("coalesce(category, '*')"), unique=True),
    )


class SlaEvent(Base):
    """started / paused / resumed / retargeted / warning / breached / stopped — with the deadline at that moment."""

    __tablename__ = "sla_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(16))
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
