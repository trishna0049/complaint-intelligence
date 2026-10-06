"""Kafka plumbing (aiokafka): topic administration, the outbox relay and the consumer loop."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.events.consumer import Consumer
from app.events.envelope import Envelope, all_topics, dlq_topic, topic
from app.models import DeadLetter, OutboxEvent

log = logging.getLogger("app.events")
PARTITIONS = 3
RELAY_BATCH = 200


def _servers() -> str:
    return get_settings().kafka_bootstrap_servers


def group_id(consumer: Consumer) -> str:
    return f"{get_settings().events_prefix}.{consumer.name}"


# ------------------------------------------------------------------------------------------------ topics
async def ensure_topics(*, reset: bool = False) -> list[str]:
    """Create the topics for EVENTS_PREFIX (idempotent). `reset` deletes them first — and with them the consumer
    groups' offsets (used by the e2e run, whose database is recreated every time)."""
    admin = AIOKafkaAdminClient(bootstrap_servers=_servers())
    await admin.start()
    try:
        wanted = all_topics()
        if reset:
            existing = set(await admin.list_topics())
            doomed = [t for t in wanted if t in existing]
            if doomed:
                await admin.delete_topics(doomed)
                await asyncio.sleep(2)  # deletion is asynchronous on the broker
            # The consumer groups' committed offsets are removed by Kafka together with the deleted topics, so the
            # workers read the recreated topics from the beginning.
        existing = set(await admin.list_topics())
        missing = [NewTopic(t, num_partitions=PARTITIONS, replication_factor=1) for t in wanted if t not in existing]
        if missing:
            await admin.create_topics(missing)
        return [t.name for t in missing]
    finally:
        await admin.close()


def producer() -> AIOKafkaProducer:
    return AIOKafkaProducer(
        bootstrap_servers=_servers(),
        acks="all",
        enable_idempotence=True,  # no duplicates from producer retries
        value_serializer=lambda v: json.dumps(v).encode(),
        key_serializer=lambda k: str(k).encode() if k is not None else None,
    )


# ------------------------------------------------------------------------------------------------ relay
async def relay_once(prod: AIOKafkaProducer) -> int:
    """Publish the next batch of outbox rows. Rows are locked (SKIP LOCKED, so several relays can run) and marked
    published only after Kafka acknowledged them; a failure leaves them for the next round."""
    async with SessionLocal() as db:
        rows = (
            await db.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.id)
                .limit(RELAY_BATCH)
                .with_for_update(skip_locked=True)
            )
        ).all()
        if not rows:
            return 0
        ids = [r.id for r in rows]  # read before a rollback would expire the rows
        try:
            futures = [await prod.send(topic(r.event_type), value=r.envelope, key=r.ticket_id) for r in rows]
            await asyncio.gather(*futures)
        except Exception as exc:
            await db.rollback()
            async with SessionLocal() as err_db:
                await err_db.execute(
                    update(OutboxEvent)
                    .where(OutboxEvent.id.in_(ids))
                    .values(publish_attempts=OutboxEvent.publish_attempts + 1, last_error=str(exc)[:2000])
                )
                await err_db.commit()
            raise
        now = datetime.now(UTC)
        for r in rows:
            r.published_at = now
            r.publish_attempts += 1
        await db.commit()
        return len(rows)


async def run_relay(stop: asyncio.Event) -> None:
    s = get_settings()
    prod = producer()
    await prod.start()
    log.info("outbox relay started (%s)", _servers())
    backoff = s.outbox_poll_seconds
    try:
        while not stop.is_set():
            try:
                sent = await relay_once(prod)
                backoff = s.outbox_poll_seconds
                if sent:
                    log.info("relay published %d events", sent)
                    continue
            except Exception:
                log.exception("relay failed; retrying in %.1fs", backoff)
                backoff = min(backoff * 2, 30)
            try:
                await asyncio.wait_for(stop.wait(), timeout=backoff)
            except TimeoutError:
                pass
    finally:
        await prod.stop()


# ------------------------------------------------------------------------------------------------ consumers
async def run_consumer(consumer: Consumer, stop: asyncio.Event) -> None:
    """Consume this worker's topics, one message at a time, committing the offset only after the event was
    processed, skipped as a duplicate, or dead-lettered — so nothing is lost if the worker crashes."""
    kafka = AIOKafkaConsumer(
        *[topic(t) for t in consumer.event_types],
        bootstrap_servers=_servers(),
        group_id=group_id(consumer),
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        value_deserializer=lambda b: b,
    )
    dlq_producer = producer()
    await kafka.start()
    await dlq_producer.start()

    async def publish_dead_letter(letter: DeadLetter) -> None:
        await dlq_producer.send_and_wait(
            dlq_topic(),
            value={
                "dead_letter_id": letter.id,
                "consumer": letter.consumer,
                "error": letter.error,
                "envelope": letter.envelope,
            },
            key=letter.ticket_id,
        )

    log.info("%s consuming %s", consumer.name, ", ".join(topic(t) for t in consumer.event_types))
    try:
        while not stop.is_set():
            batch = await kafka.getmany(timeout_ms=1000, max_records=50)
            for tp, messages in batch.items():
                for msg in messages:
                    try:
                        env = Envelope.model_validate(json.loads(msg.value))
                    except Exception as exc:  # a malformed message can never succeed: straight to the DLQ table
                        log.error("%s: unreadable message at %s:%s: %s", consumer.name, tp, msg.offset, exc)
                        await _unreadable(consumer, msg.value, str(exc))
                    else:
                        await consumer.process(env, dlq=publish_dead_letter)
                    await kafka.commit({TopicPartition(tp.topic, tp.partition): msg.offset + 1})
    finally:
        await kafka.stop()
        await dlq_producer.stop()


async def _unreadable(consumer: Consumer, raw: bytes, error: str) -> None:
    import uuid

    async with SessionLocal() as db:
        db.add(
            DeadLetter(
                consumer=consumer.name,
                event_id=uuid.uuid4(),
                event_type="unreadable",
                ticket_id=None,
                envelope={"raw": raw.decode(errors="replace")[:10_000]},
                error=f"unreadable message: {error}"[:4000],
                attempts=0,
                status="waiting",
            )
        )
        await db.commit()
