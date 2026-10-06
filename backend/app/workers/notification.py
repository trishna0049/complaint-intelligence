"""Notification worker.

* ticket.assigned  -> tell the assignee (unless they took the ticket themselves)
* ticket.escalated -> alert every Admin (not the one who escalated); critical when the SLA engine escalated
* sla.warning      -> warn the assignee (no assignee: the Admins)
* sla.breached     -> alert the Admins and the assignee

Notifications reach open browsers at once (SSE via Redis pub/sub) and, for escalations and SLA alerts, the inbox when
SMTP is configured — see app/services/notifications.py.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.events.consumer import Consumer
from app.events.envelope import Envelope, EventType
from app.models import Ticket
from app.services import notifications as svc


async def _ticket(db: AsyncSession, env: Envelope) -> Ticket | None:
    return await db.get(Ticket, env.ticket_id) if env.ticket_id is not None else None


def _due(deadline: str | None) -> str:
    if not deadline:
        return ""
    return datetime.fromisoformat(deadline).strftime("%d %b %Y, %H:%M UTC")


async def on_assigned(db: AsyncSession, env: Envelope) -> None:
    t = await _ticket(db, env)
    assignee_id = env.payload.get("assignee_id")
    if t is None or assignee_id is None or assignee_id == env.actor.id:
        return
    user = await svc.active_user(db, assignee_id)
    if user is None:
        return
    how = "Routed to you by the rules" if env.actor.id is None else f"Assigned to you by {env.actor.name}"
    await svc.notify(
        db,
        [user],
        type="ticket_assigned",
        ticket=t,
        title=f"{t.ticket_number} assigned to you",
        message=f"{how}: “{t.subject}” · {t.priority} priority · {t.category or 'uncategorised'}.",
    )


async def on_escalated(db: AsyncSession, env: Envelope) -> None:
    t = await _ticket(db, env)
    if t is None:
        return
    auto = bool(env.payload.get("auto"))
    admins = [a for a in await svc.active_admins(db) if a.id != env.actor.id]
    by = "the SLA engine" if auto else env.actor.name
    await svc.notify(
        db,
        admins,
        type="ticket_escalated",
        ticket=t,
        severity="critical" if auto else "warning",
        title=f"{t.ticket_number} escalated",
        message=f"Escalated by {by}: {env.payload.get('reason') or 'no reason given'} — “{t.subject}”.",
    )


async def on_sla_warning(db: AsyncSession, env: Envelope) -> None:
    t = await _ticket(db, env)
    if t is None:
        return
    assignee = await svc.active_user(db, t.assignee_id)
    recipients = [assignee] if assignee else await svc.active_admins(db)
    await svc.notify(
        db,
        recipients,
        type="sla_warning",
        ticket=t,
        severity="warning",
        title=f"SLA at risk: {t.ticket_number}",
        message=f"80 % of the SLA is used — due {_due(env.payload.get('deadline'))}. “{t.subject}”.",
    )


async def on_sla_breached(db: AsyncSession, env: Envelope) -> None:
    t = await _ticket(db, env)
    if t is None:
        return
    assignee = await svc.active_user(db, t.assignee_id)
    recipients = [*await svc.active_admins(db), *([assignee] if assignee else [])]
    owner = f" (assigned to {assignee.name})" if assignee else " (unassigned)"
    await svc.notify(
        db,
        recipients,
        type="sla_breached",
        ticket=t,
        severity="critical",
        title=f"SLA breached: {t.ticket_number}",
        message=f"The deadline passed{owner}; the ticket is escalated automatically. “{t.subject}”.",
    )


CONSUMER = Consumer(
    name="notification-worker",
    description="In-app alerts (and optional e-mail)",
    handlers={
        EventType.TICKET_ASSIGNED: on_assigned,
        EventType.TICKET_ESCALATED: on_escalated,
        EventType.SLA_WARNING: on_sla_warning,
        EventType.SLA_BREACHED: on_sla_breached,
    },
)
