"""AI worker.

* ticket.created  -> NLP triage (category, intent, sentiment, entities, priority rules), routing rules (team +
  least-busy agent) and the MiniLM embedding, in one transaction. Emits ai.analysis.completed and ticket.assigned.
* ticket.updated / ticket.resolved -> analytics + embeddings: keep the ticket's embedding current (and the cached
  dashboard is invalidated after every processed event by the consumer framework).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.events.consumer import Consumer
from app.events.envelope import Envelope, EventType
from app.repositories import tickets as repo
from app.services import retrieval
from app.services import tickets as tickets_svc


async def on_ticket_created(db: AsyncSession, env: Envelope) -> None:
    if env.ticket_id is not None:
        await tickets_svc.triage_ticket(db, env.ticket_id)


async def on_ticket_changed(db: AsyncSession, env: Envelope) -> None:
    if env.ticket_id is None:
        return
    t = await repo.get(db, env.ticket_id)
    if t is not None:
        await retrieval.embed_ticket(db, t)


CONSUMER = Consumer(
    name="ai-worker",
    description="Triage, routing and embeddings",
    handlers={
        EventType.TICKET_CREATED: on_ticket_created,
        EventType.TICKET_UPDATED: on_ticket_changed,
        EventType.TICKET_RESOLVED: on_ticket_changed,
    },
)
