"""The event catalogue (spec: "Kafka events") and the message envelope every event travels in.

Each event carries event_id, type, timestamp, ticket_id, actor and payload. One Kafka topic per event type
(`<prefix>.<type>`, e.g. complaints.ticket.created), keyed by ticket id so a ticket's events stay in order.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import get_settings


class EventType(StrEnum):
    TICKET_CREATED = "ticket.created"  # a ticket is submitted                 -> AI worker
    AI_ANALYSIS_COMPLETED = "ai.analysis.completed"  # triage finished      -> LLM worker, SLA worker
    TICKET_ASSIGNED = "ticket.assigned"  # routed or reassigned             -> notification worker
    TICKET_UPDATED = "ticket.updated"  # status / category changes          -> analytics, embeddings (AI worker)
    TICKET_RESOLVED = "ticket.resolved"  # resolved                         -> analytics, embeddings (AI worker)
    TICKET_ESCALATED = "ticket.escalated"  # manual or automatic             -> notification worker (alerts admin)
    SLA_WARNING = "sla.warning"  # 80% of SLA time used                     -> notification worker (alerts agent)
    SLA_BREACHED = "sla.breached"  # 100% of SLA time used                   -> auto-escalation, alerts admin


class Actor(BaseModel):
    id: int | None = None  # None = the system (a worker, the SLA engine)
    name: str = "system"
    role: str | None = None


class Envelope(BaseModel):
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    type: EventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ticket_id: int | None = None
    actor: Actor = Field(default_factory=Actor)
    payload: dict[str, Any] = Field(default_factory=dict)
    # Set when an Admin replays a dead letter (same event_id, so only the consumer that failed runs again).
    replay_of: int | None = None


def topic(event_type: EventType | str) -> str:
    return f"{get_settings().events_prefix}.{EventType(event_type).value}"


def dlq_topic() -> str:
    return f"{get_settings().events_prefix}.dlq"


def all_topics() -> list[str]:
    return [topic(t) for t in EventType] + [dlq_topic()]
