"""SLA worker.

* ai.analysis.completed -> start the SLA clock (deadline from the SLA policy for the ticket's priority/category)
* ticket.updated        -> pause while WAITING_CUSTOMER, resume afterwards
* ticket.resolved / ticket.escalated -> stop the clock / record escalation
* periodic scan         -> sla.warning at 80 %, sla.breached at 100 % (once each), auto-escalation on breach

The subscriptions are live from step 8 of the build; the SLA engine behind them is step 9 (docs/GAP_REPORT.md).
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.events.consumer import Consumer
from app.events.envelope import Envelope, EventType

log = logging.getLogger("app.workers.sla")


async def on_ticket_event(db: AsyncSession, env: Envelope) -> None:
    log.debug("sla worker received %s for ticket %s (SLA engine: build step 9)", env.type, env.ticket_id)


CONSUMER = Consumer(
    name="sla-worker",
    description="SLA clocks, warnings, breaches and auto-escalation",
    handlers={
        EventType.AI_ANALYSIS_COMPLETED: on_ticket_event,
        EventType.TICKET_UPDATED: on_ticket_event,
        EventType.TICKET_RESOLVED: on_ticket_event,
        EventType.TICKET_ESCALATED: on_ticket_event,
    },
)
