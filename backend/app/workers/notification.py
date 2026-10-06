"""Notification worker.

* ticket.assigned  -> tell the assignee
* ticket.escalated -> alert the admins
* sla.warning      -> warn the assignee
* sla.breached     -> alert the admins

The subscriptions are live from step 8 of the build; the notifications table, the SSE stream and optional e-mail
behind them are step 10 (docs/GAP_REPORT.md).
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.events.consumer import Consumer
from app.events.envelope import Envelope, EventType

log = logging.getLogger("app.workers.notification")


async def on_notify_event(db: AsyncSession, env: Envelope) -> None:
    log.debug("notification worker received %s for ticket %s (notifications: build step 10)", env.type, env.ticket_id)


CONSUMER = Consumer(
    name="notification-worker",
    description="In-app alerts (and optional e-mail)",
    handlers={
        EventType.TICKET_ASSIGNED: on_notify_event,
        EventType.TICKET_ESCALATED: on_notify_event,
        EventType.SLA_WARNING: on_notify_event,
        EventType.SLA_BREACHED: on_notify_event,
    },
)
