"""SLA worker.

* ai.analysis.completed -> start the SLA clock (deadline from the SLA policy for the ticket's priority/category)
* ticket.updated        -> pause while WAITING_CUSTOMER, resume afterwards (also after a reopen); re-target when a
                           category correction changed the priority
* ticket.resolved       -> stop the clock: met, or breached
* sla.breached          -> automatic escalation (the admins are alerted by the notification worker)
* scanner (in the worker process, every SLA_SCAN_SECONDS) -> sla.warning at 80 %, sla.breached at 100 %, once each
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.events.consumer import Consumer
from app.events.envelope import Envelope, EventType
from app.services import sla


async def on_analysis_completed(db: AsyncSession, env: Envelope) -> None:
    if env.ticket_id is not None:
        await sla.start(db, env.ticket_id)


async def on_ticket_updated(db: AsyncSession, env: Envelope) -> None:
    if env.ticket_id is None:
        return
    change = env.payload.get("change")
    if change == "status_changed":
        await sla.on_status_change(db, env.ticket_id, env.payload.get("from"), env.payload.get("to"))
    elif change in ("category_corrected", "category_confirmed"):
        await sla.retarget(db, env.ticket_id)


async def on_ticket_resolved(db: AsyncSession, env: Envelope) -> None:
    if env.ticket_id is not None:
        await sla.on_status_change(db, env.ticket_id, env.payload.get("from"), "RESOLVED")


async def on_breached(db: AsyncSession, env: Envelope) -> None:
    if env.ticket_id is not None:
        await sla.escalate_on_breach(db, env.ticket_id)


CONSUMER = Consumer(
    name="sla-worker",
    description="SLA clocks, warnings, breaches and auto-escalation",
    handlers={
        EventType.AI_ANALYSIS_COMPLETED: on_analysis_completed,
        EventType.TICKET_UPDATED: on_ticket_updated,
        EventType.TICKET_RESOLVED: on_ticket_resolved,
        EventType.SLA_BREACHED: on_breached,
    },
)
