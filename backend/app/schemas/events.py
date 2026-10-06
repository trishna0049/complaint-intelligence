from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DeadLetterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    consumer: str
    event_id: uuid.UUID
    event_type: str
    ticket_id: int | None
    envelope: dict[str, Any]
    error: str
    attempts: int
    status: Literal["waiting", "replayed", "discarded"]
    failed_at: datetime
    resolved_at: datetime | None
    resolved_by_id: int | None


class DiscardRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class OutboxStatus(BaseModel):
    pending: int
    oldest_pending_seconds: float | None
    failing: int
    last_published_at: datetime | None


class ConsumerStatus(BaseModel):
    name: str
    description: str
    events: list[str]
    processed_total: int
    processed_last_hour: int
    last_processed_at: datetime | None
    dead_letters_waiting: int


class PipelineStatus(BaseModel):
    mode: Literal["kafka", "inline"]
    prefix: str
    kafka_bootstrap_servers: str | None
    retries: int
    kafka_ui_url: str | None = None
    outbox: OutboxStatus
    consumers: list[ConsumerStatus]
