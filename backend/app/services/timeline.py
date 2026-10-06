"""The ticket timeline and the domain events derived from it — one place, so every change that matters to the
rest of the system (workers, notifications, SLA) is published exactly when it is written to the timeline, in the
same transaction.

    timeline event                     -> Kafka event
    created                            -> ticket.created
    triaged                            -> ai.analysis.completed
    assigned, routed (outcome assigned)-> ticket.assigned
    status_changed (to RESOLVED)       -> ticket.resolved
    status_changed (anything else)     -> ticket.updated
    category_corrected / _confirmed    -> ticket.updated
    escalated                          -> ticket.escalated
    sla_warning / sla_breached         -> sla.warning / sla.breached
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.events.envelope import EventType
from app.events.outbox import emit
from app.models import Ticket, User
from app.repositories import tickets as repo


def domain_events(event_type: str, metadata: dict[str, Any]) -> list[EventType]:
    if event_type == "created":
        return [EventType.TICKET_CREATED]
    if event_type == "triaged":
        return [EventType.AI_ANALYSIS_COMPLETED]
    if event_type == "assigned" or (event_type == "routed" and metadata.get("outcome") == "assigned"):
        return [EventType.TICKET_ASSIGNED]
    if event_type == "status_changed":
        return [EventType.TICKET_RESOLVED if metadata.get("to") == "RESOLVED" else EventType.TICKET_UPDATED]
    if event_type in ("category_corrected", "category_confirmed"):
        return [EventType.TICKET_UPDATED]
    if event_type == "escalated":
        return [EventType.TICKET_ESCALATED]
    if event_type == "sla_warning":
        return [EventType.SLA_WARNING]
    if event_type == "sla_breached":
        return [EventType.SLA_BREACHED]
    return []


def record(db: AsyncSession, t: Ticket, event_type: str, actor: User | None, **metadata: Any) -> None:
    """Write a timeline row and its domain events (outbox) into the caller's transaction."""
    repo.add_event(db, t.id, event_type, actor.id if actor else None, metadata)
    for kind in domain_events(event_type, metadata):
        emit(db, kind, ticket=t, actor=actor, payload={"change": event_type, **metadata})
