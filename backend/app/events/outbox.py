"""Writing events: an outbox row in the caller's transaction (it commits — or rolls back — with the change)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.events.envelope import Actor, Envelope, EventType
from app.models import OutboxEvent, Ticket, User


def actor_of(user: User | None) -> Actor:
    return Actor(id=user.id, name=user.name, role=user.role) if user else Actor()


def ticket_snapshot(t: Ticket) -> dict[str, Any]:
    """What consumers usually need without a database read."""
    return {
        "ticket_number": t.ticket_number,
        "status": t.status,
        "priority": t.priority,
        "category": t.category,
        "assignee_id": t.assignee_id,
        "team_id": t.team_id,
    }


def emit(
    db: AsyncSession,
    event_type: EventType,
    *,
    ticket: Ticket | None = None,
    actor: User | None = None,
    payload: dict[str, Any] | None = None,
) -> Envelope:
    env = Envelope(
        type=event_type,
        ticket_id=ticket.id if ticket else None,
        actor=actor_of(actor),
        payload={**(ticket_snapshot(ticket) if ticket else {}), **(payload or {})},
    )
    db.add(write_row(env))
    return env


def write_row(env: Envelope) -> OutboxEvent:
    return OutboxEvent(
        event_id=env.event_id, event_type=env.type.value, ticket_id=env.ticket_id, envelope=env.model_dump(mode="json")
    )
