"""Event tables: the transactional outbox, consumer idempotency and the dead-letter queue."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class OutboxEvent(Base):
    """An event saved in the same transaction as the change it describes; the relay publishes it to Kafka
    (outbox pattern: nothing is lost if Kafka is down, nothing is published for a rolled-back change)."""

    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Not unique: an Admin replay of a dead letter re-publishes the original event id (consumers that already
    # handled it skip it via processed_events; only the one that failed runs again).
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    event_type: Mapped[str] = mapped_column(String(48))
    ticket_id: Mapped[int | None] = mapped_column(Integer)
    envelope: Mapped[dict[str, Any]] = mapped_column(JSONB)  # the full message (event_id, type, timestamp, ...)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_outbox_unpublished", "id", postgresql_where=text("published_at IS NULL")),)


class ProcessedEvent(Base):
    """Idempotency: one row per (consumer, event) handled, committed together with the handler's own writes."""

    __tablename__ = "processed_events"

    consumer: Mapped[str] = mapped_column(String(48), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(48))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class DeadLetter(Base):
    """An event a consumer still failed after all retries. Waits here (and on the DLQ topic) for an Admin to replay
    or discard it."""

    __tablename__ = "dead_letters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    consumer: Mapped[str] = mapped_column(String(48), index=True)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    event_type: Mapped[str] = mapped_column(String(48))
    ticket_id: Mapped[int | None] = mapped_column(Integer, index=True)
    envelope: Mapped[dict[str, Any]] = mapped_column(JSONB)
    error: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default="waiting", index=True)  # waiting | replayed | discarded
    failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
