"""Admin view of the event pipeline: outbox lag, what each worker processed, and the dead-letter queue (replay or
discard, both audited)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.events import bus
from app.events.envelope import Envelope
from app.events.outbox import write_row
from app.models import DeadLetter, OutboxEvent, ProcessedEvent, User
from app.repositories import users as users_repo
from app.workers.registry import CONSUMERS


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail={"code": "conflict", "message": message})


async def list_dead_letters(
    db: AsyncSession, *, state: str | None, consumer: str | None, page: int, page_size: int
) -> tuple[list[DeadLetter], int]:
    stmt = select(DeadLetter)
    if state:
        stmt = stmt.where(DeadLetter.status == state)
    if consumer:
        stmt = stmt.where(DeadLetter.consumer == consumer)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = await db.scalars(stmt.order_by(DeadLetter.id.desc()).limit(page_size).offset((page - 1) * page_size))
    return list(rows.all()), total


async def _waiting(db: AsyncSession, letter_id: int) -> DeadLetter:
    letter = await db.get(DeadLetter, letter_id, with_for_update=True)
    if letter is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Dead letter not found")
    if letter.status != "waiting":
        raise _conflict(f"This dead letter was already {letter.status}.")
    return letter


async def replay(db: AsyncSession, admin: User, letter_id: int) -> DeadLetter:
    """Publish the original event again (same event_id): consumers that handled it skip it as a duplicate, the one
    that failed processes it — with today's code and data."""
    letter = await _waiting(db, letter_id)
    if letter.event_type == "unreadable":
        raise _conflict("An unreadable message can't be replayed — discard it.")
    env = Envelope.model_validate(letter.envelope).model_copy(update={"replay_of": letter.id})
    db.add(write_row(env))
    letter.status, letter.resolved_at, letter.resolved_by_id = "replayed", datetime.now(UTC), admin.id
    users_repo.audit(
        db,
        "dlq.replay",
        actor_id=admin.id,
        resource_type="dead_letter",
        resource_id=letter.id,
        metadata={
            "consumer": letter.consumer,
            "event_type": letter.event_type,
            "event_id": str(letter.event_id),
            "ticket_id": letter.ticket_id,
        },
    )
    await db.commit()
    await bus.after_commit()
    await db.refresh(letter)
    return letter


async def discard(db: AsyncSession, admin: User, letter_id: int, reason: str | None) -> DeadLetter:
    letter = await _waiting(db, letter_id)
    letter.status, letter.resolved_at, letter.resolved_by_id = "discarded", datetime.now(UTC), admin.id
    users_repo.audit(
        db,
        "dlq.discard",
        actor_id=admin.id,
        resource_type="dead_letter",
        resource_id=letter.id,
        metadata={"consumer": letter.consumer, "event_type": letter.event_type, "reason": reason},
    )
    await db.commit()
    await db.refresh(letter)
    return letter


async def pipeline_status(db: AsyncSession) -> dict[str, Any]:
    s = get_settings()
    now = datetime.now(UTC)
    pending, oldest = (
        await db.execute(
            select(func.count(), func.min(OutboxEvent.created_at)).where(OutboxEvent.published_at.is_(None))
        )
    ).one()
    last_published = await db.scalar(select(func.max(OutboxEvent.published_at)))
    failing = await db.scalar(
        select(func.count()).where(OutboxEvent.published_at.is_(None), OutboxEvent.publish_attempts > 0)
    )
    hour_ago = now - timedelta(hours=1)
    processed = dict(
        (await db.execute(select(ProcessedEvent.consumer, func.count()).group_by(ProcessedEvent.consumer))).all()
    )
    recent = dict(
        (
            await db.execute(
                select(ProcessedEvent.consumer, func.count())
                .where(ProcessedEvent.processed_at >= hour_ago)
                .group_by(ProcessedEvent.consumer)
            )
        ).all()
    )
    last_seen = dict(
        (
            await db.execute(
                select(ProcessedEvent.consumer, func.max(ProcessedEvent.processed_at)).group_by(ProcessedEvent.consumer)
            )
        ).all()
    )
    waiting = dict(
        (
            await db.execute(
                select(DeadLetter.consumer, func.count())
                .where(DeadLetter.status == "waiting")
                .group_by(DeadLetter.consumer)
            )
        ).all()
    )
    return {
        "mode": s.events_mode,
        "prefix": s.events_prefix,
        "kafka_bootstrap_servers": s.kafka_bootstrap_servers if s.events_mode == "kafka" else None,
        "retries": s.event_retries,
        "kafka_ui_url": s.kafka_ui_url if s.events_mode == "kafka" else None,
        "outbox": {
            "pending": pending or 0,
            "oldest_pending_seconds": round((now - oldest).total_seconds(), 1) if oldest else None,
            "failing": failing or 0,
            "last_published_at": last_published,
        },
        "consumers": [
            {
                "name": c.name,
                "description": c.description,
                "events": [t.value for t in c.event_types],
                "processed_total": processed.get(c.name, 0),
                "processed_last_hour": recent.get(c.name, 0),
                "last_processed_at": last_seen.get(c.name),
                "dead_letters_waiting": waiting.get(c.name, 0),
            }
            for c in CONSUMERS
        ],
    }
