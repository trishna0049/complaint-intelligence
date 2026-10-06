"""After-commit hook. Kafka mode: nothing to do — the relay publishes the outbox. Inline mode: the outbox is drained
right here, in the API process, through the very same consumers (idempotency, retries, DLQ included), so unit tests
and broker-less demos behave like the real pipeline, only synchronously."""

from __future__ import annotations

import contextvars
import logging

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.events.envelope import Envelope
from app.models import OutboxEvent

log = logging.getLogger("app.events")
_draining: contextvars.ContextVar[bool] = contextvars.ContextVar("draining", default=False)
BATCH = 50


async def after_commit() -> None:
    if get_settings().events_mode == "inline":
        await drain()


async def _claim(limit: int) -> list[Envelope]:
    """Take unpublished outbox rows (SKIP LOCKED: concurrent requests never handle the same row) and mark them."""
    from datetime import UTC, datetime

    async with SessionLocal() as db:
        rows = (
            await db.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        now = datetime.now(UTC)
        for row in rows:
            row.published_at = now
        await db.commit()
        return [Envelope.model_validate(r.envelope) for r in rows]


async def drain() -> int:
    """Hand every pending outbox event to every consumer subscribed to its type, until none is left (handlers may
    emit more events). Re-entrant calls (a handler's own commit) are no-ops; the outer loop picks their events up."""
    if _draining.get():
        return 0
    from app.workers.registry import CONSUMERS

    token = _draining.set(True)
    handled = 0
    try:
        while batch := await _claim(BATCH):
            for env in batch:
                for consumer in CONSUMERS:
                    if env.type in consumer.handlers:
                        await consumer.process(env)
                handled += 1
    finally:
        _draining.reset(token)
    return handled
