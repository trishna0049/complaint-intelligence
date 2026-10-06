"""The consumer framework every worker uses — in Kafka mode and in inline mode alike.

For each event and consumer:
1. Idempotency: if processed_events already has (consumer, event_id), the event is skipped. Otherwise the handler
   runs and the processed_events row is committed in the SAME transaction as the handler's writes, so an event's
   effect is applied exactly once even if Kafka delivers it twice (redelivery after a crash, an Admin replay...).
2. Retries: a handler that raises is retried EVENT_RETRIES times (3) with exponential backoff.
3. Dead-letter queue: after the last retry the event is stored in dead_letters (and, in Kafka mode, published to
   the <prefix>.dlq topic) for an Admin to replay or discard. The consumer then moves on — one bad event never
   blocks the queue.

Handlers must not commit their writes themselves (reads may commit, e.g. before a slow LLM call).
Side effects outside the database (Redis pub/sub, e-mail) are registered with `after_commit(db, coroutine_fn)` and run
only once the transaction committed; their failure is logged and never undoes the handled event.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.events.envelope import Envelope, EventType
from app.models import DeadLetter, ProcessedEvent

log = logging.getLogger("app.events")

Handler = Callable[[AsyncSession, Envelope], Awaitable[None]]
DlqPublisher = Callable[[DeadLetter], Awaitable[None]]


class Outcome(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    DEAD_LETTERED = "dead_lettered"
    IGNORED = "ignored"  # not an event type this consumer handles


@dataclass
class Consumer:
    name: str  # also the Kafka consumer group (prefixed) and the processed_events.consumer value
    handlers: dict[EventType, Handler]
    description: str = ""

    @property
    def event_types(self) -> list[EventType]:
        return list(self.handlers)

    async def process(self, env: Envelope, *, dlq: DlqPublisher | None = None) -> Outcome:
        handler = self.handlers.get(env.type)
        if handler is None:
            return Outcome.IGNORED
        s = get_settings()
        attempts = s.event_retries + 1
        error = ""
        for attempt in range(1, attempts + 1):
            try:
                outcome = await self._attempt(handler, env)
                log.info("%s %s %s %s", self.name, env.type, env.event_id, outcome)
                return outcome
            except Exception as exc:  # any failure is retried, then dead-lettered
                error = f"{type(exc).__name__}: {exc}"
                log.warning(
                    "%s failed %s %s (attempt %d/%d): %s", self.name, env.type, env.event_id, attempt, attempts, error
                )
                if attempt < attempts:
                    await asyncio.sleep(s.event_retry_backoff_seconds * 2 ** (attempt - 1))
        letter = await self._dead_letter(env, error, attempts)
        if dlq is not None:
            try:
                await dlq(letter)
            except Exception:  # the dead_letters row is the source of truth; the topic is a copy
                log.exception("could not publish dead letter %s to the DLQ topic", letter.id)
        return Outcome.DEAD_LETTERED

    async def _attempt(self, handler: Handler, env: Envelope) -> Outcome:
        from app.events import bus  # local: bus imports the worker registry
        from app.services.analytics import invalidate_cache

        async with SessionLocal() as db:
            if await db.get(ProcessedEvent, (self.name, env.event_id)) is not None:
                return Outcome.DUPLICATE
            await handler(db, env)
            db.add(ProcessedEvent(consumer=self.name, event_id=env.event_id, event_type=env.type.value))
            try:
                await db.commit()
            except IntegrityError:  # another instance of this consumer finished it first
                await db.rollback()
                return Outcome.DUPLICATE
            after = db.info.pop("after_commit", [])
        for callback in after:  # side effects that must only happen once the writes are durable (pub/sub, e-mail)
            try:
                await callback()
            except Exception:
                log.exception("%s: after-commit step failed for %s", self.name, env.event_id)
        await invalidate_cache()
        await bus.after_commit()
        return Outcome.PROCESSED

    async def _dead_letter(self, env: Envelope, error: str, attempts: int) -> DeadLetter:
        log.error("%s dead-lettered %s %s after %d attempts: %s", self.name, env.type, env.event_id, attempts, error)
        async with SessionLocal() as db:
            letter = DeadLetter(
                consumer=self.name,
                event_id=env.event_id,
                event_type=env.type.value,
                ticket_id=env.ticket_id,
                envelope=env.model_dump(mode="json"),
                error=error[:4000],
                attempts=attempts,
                status="waiting",
            )
            db.add(letter)
            await db.commit()
            await db.refresh(letter)
            return letter


def after_commit(db: AsyncSession, callback: Callable[[], Awaitable[None]]) -> None:
    """Run `callback` after this session's transaction commits (in the consumer framework)."""
    db.info.setdefault("after_commit", []).append(callback)
