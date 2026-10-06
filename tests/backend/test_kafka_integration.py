"""Integration tests on a real Kafka broker (the Compose `kafka` service): the outbox relay and the four workers
consuming real topics — the full ticket flow, idempotency under duplicate delivery, retries and the DLQ topic, and an
Admin replay through Kafka. Each test uses its own topic prefix; skipped when no broker is reachable."""

from __future__ import annotations

import asyncio
import json
import socket
import time
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.events import kafka
from app.events.envelope import Envelope, dlq_topic, topic
from app.models import DeadLetter, OutboxEvent, ProcessedEvent, Ticket, TicketEvent
from app.workers import registry


def _broker_up() -> bool:
    host, _, port = get_settings().kafka_bootstrap_servers.partition(":")
    try:
        with socket.create_connection((host, int(port or 9092)), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _broker_up(), reason="Kafka not reachable (.\\scripts\\dev.ps1 up)")

PAYMENTS = {"description": "I was charged twice for my order of ₹12,500 and nobody helps", "channel": "Email"}


@pytest.fixture
async def pipeline(monkeypatch) -> AsyncIterator[str]:
    """Relay + the four workers on a fresh topic prefix, in this event loop."""
    prefix = f"it-{uuid.uuid4().hex[:8]}"
    s = get_settings()
    monkeypatch.setattr(s, "events_mode", "kafka")
    monkeypatch.setattr(s, "events_prefix", prefix)
    monkeypatch.setattr(s, "outbox_poll_seconds", 0.2)
    await kafka.ensure_topics()
    stop = asyncio.Event()
    tasks = [asyncio.create_task(kafka.run_relay(stop))]
    tasks += [asyncio.create_task(kafka.run_consumer(c, stop)) for c in registry.CONSUMERS]
    yield prefix
    stop.set()
    await asyncio.gather(*tasks, return_exceptions=True)
    await drop(prefix)


async def drop(prefix: str) -> None:
    """Delete this test's topics from the shared broker."""
    from aiokafka.admin import AIOKafkaAdminClient

    admin = AIOKafkaAdminClient(bootstrap_servers=get_settings().kafka_bootstrap_servers)
    await admin.start()
    try:
        # The consumer groups' committed offsets go with the deleted topics (Kafka removes offsets of deleted topics).
        await admin.delete_topics([t for t in await admin.list_topics() if t.startswith(prefix + ".")])
    finally:
        await admin.close()


async def wait_for(predicate, timeout: float = 60.0, what: str = "condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result := await predicate():
            return result
        await asyncio.sleep(0.25)
    raise AssertionError(f"timed out waiting for {what}")


async def ticket_status(tid: int) -> str:
    async with SessionLocal() as db:
        return (await db.get(Ticket, tid)).status


async def count(model, *where) -> int:
    async with SessionLocal() as db:
        return await db.scalar(select(func.count()).select_from(model).where(*where)) or 0


async def test_full_flow_through_kafka(client, org, pipeline):
    res = await client.post("/api/v1/tickets", json=PAYMENTS)
    t = res.json()
    assert res.status_code == 201 and t["status"] == "NEW"  # instant: the AI work is asynchronous
    await wait_for(lambda: _is(t["id"], "ASSIGNED"), what="triage + routing by the AI worker")
    detail = (await client.get(f"/api/v1/tickets/{t['id']}")).json()
    assert detail["category"] == "Payments related" and detail["assignee"]["name"] == "Arjun Agent"
    assert [e["event_type"] for e in detail["timeline"]][:3] == ["created", "triaged", "routed"]
    await wait_for(
        lambda: _processed({"ai-worker", "llm-worker", "sla-worker", "notification-worker"}),
        what="every worker to process its events",
    )
    assert await count(OutboxEvent, OutboxEvent.published_at.is_(None)) == 0  # the relay published everything


async def _is(tid: int, status: str) -> bool:
    return await ticket_status(tid) == status


async def _processed(consumers: set[str]) -> bool:
    async with SessionLocal() as db:
        seen = set((await db.scalars(select(ProcessedEvent.consumer).distinct())).all())
    return consumers <= seen


async def test_duplicate_delivery_is_processed_once(client, org, pipeline):
    t = (await client.post("/api/v1/tickets", json=PAYMENTS)).json()
    await wait_for(lambda: _is(t["id"], "ASSIGNED"), what="first processing")
    async with SessionLocal() as db:
        created = await db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "ticket.created"))
    prod = kafka.producer()
    await prod.start()
    try:
        for _ in range(3):  # Kafka at-least-once: the same message again
            await prod.send_and_wait(topic("ticket.created"), value=created.envelope, key=t["id"])
    finally:
        await prod.stop()
    await asyncio.sleep(4)
    assert (
        await count(
            ProcessedEvent, ProcessedEvent.consumer == "ai-worker", ProcessedEvent.event_type == "ticket.created"
        )
        == 1
    )
    assert await count(TicketEvent, TicketEvent.ticket_id == t["id"], TicketEvent.event_type == "triaged") == 1


async def test_failures_retry_then_dead_letter_to_the_dlq_topic_and_replay(client, org, pipeline, monkeypatch):
    from aiokafka import AIOKafkaConsumer

    from app.ai import llm

    monkeypatch.setattr(get_settings(), "copilot_auto", True)
    monkeypatch.setattr(get_settings(), "event_retry_backoff_seconds", 0.05)
    down = {"value": True}
    real = llm.MockProvider.generate

    def flaky(self, text, context):  # type: ignore[no-untyped-def]
        if down["value"]:
            raise llm.LLMError("llm_timeout", "LLM did not answer", 504)
        return real(self, text, context)

    monkeypatch.setattr(llm.MockProvider, "generate", flaky)
    t = (await client.post("/api/v1/tickets", json=PAYMENTS)).json()
    letter = await wait_for(lambda: _letter("llm-worker"), what="the LLM worker's dead letter")
    assert letter.attempts == 4 and "LLM did not answer" in letter.error and letter.ticket_id == t["id"]

    dlq = AIOKafkaConsumer(
        dlq_topic(),
        bootstrap_servers=get_settings().kafka_bootstrap_servers,
        group_id=f"{pipeline}.dlq-reader",
        auto_offset_reset="earliest",
    )
    await dlq.start()
    try:
        msg = await asyncio.wait_for(dlq.getone(), 30)
    finally:
        await dlq.stop()
    body = json.loads(msg.value)
    assert body["dead_letter_id"] == letter.id and body["consumer"] == "llm-worker"
    assert Envelope.model_validate(body["envelope"]).type == "ai.analysis.completed"

    down["value"] = False
    assert (await client.post(f"/api/v1/admin/dlq/{letter.id}/replay")).status_code == 200
    detail = await wait_for(lambda: _with_copilot(client, t["id"]), what="the replayed draft")
    assert detail["copilot"]["draft_status"] == "pending"
    # The SLA worker had processed the original event; the replay was a duplicate for it.
    assert (
        await count(
            ProcessedEvent,
            ProcessedEvent.consumer == "sla-worker",
            ProcessedEvent.event_type == "ai.analysis.completed",
        )
        == 1
    )


async def _letter(consumer: str) -> DeadLetter | None:
    async with SessionLocal() as db:
        return await db.scalar(select(DeadLetter).where(DeadLetter.consumer == consumer))


async def _with_copilot(client, tid: int) -> dict | None:
    detail = (await client.get(f"/api/v1/tickets/{tid}")).json()
    return detail if detail["copilot"] else None


async def test_relay_keeps_events_until_kafka_accepts_them(client, org, monkeypatch):
    """Kafka down: the change is saved, its event stays in the outbox with the error, and is published once the
    broker accepts it — nothing is lost and nothing is published twice."""
    from aiokafka.errors import KafkaConnectionError

    s = get_settings()
    monkeypatch.setattr(s, "events_mode", "kafka")
    prefix = f"it-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(s, "events_prefix", prefix)
    t = (await client.post("/api/v1/tickets", json=PAYMENTS)).json()
    assert t["status"] == "NEW"

    class Down:
        async def send(self, *args, **kwargs):
            raise KafkaConnectionError("broker unreachable")

    with pytest.raises(KafkaConnectionError):
        await kafka.relay_once(Down())  # type: ignore[arg-type]
    async with SessionLocal() as db:
        row = await db.scalar(select(OutboxEvent).where(OutboxEvent.ticket_id == t["id"]))
    assert row.published_at is None and row.publish_attempts == 1 and "unreachable" in row.last_error

    await kafka.ensure_topics()
    prod = kafka.producer()
    await prod.start()
    try:
        assert await kafka.relay_once(prod) == 1
        assert await kafka.relay_once(prod) == 0  # published once
    finally:
        await prod.stop()
        await drop(prefix)
    async with SessionLocal() as db:
        row = await db.scalar(select(OutboxEvent).where(OutboxEvent.ticket_id == t["id"]))
    assert row.published_at is not None and row.publish_attempts == 2


async def test_sla_breach_escalates_through_kafka(client, org, pipeline):
    """SLA worker via the broker: the clock starts on ai.analysis.completed; a breach found by the scanner goes out as
    sla.breached and comes back to the SLA worker, which escalates the ticket automatically."""
    from datetime import timedelta

    from app.services import sla

    t = (await client.post("/api/v1/tickets", json=PAYMENTS)).json()

    async def clock_started() -> bool:
        async with SessionLocal() as db:
            return (await db.get(Ticket, t["id"])).sla_started_at is not None

    await wait_for(clock_started, what="the SLA worker to start the clock")
    async with SessionLocal() as db:
        row = await db.get(Ticket, t["id"])
        row.sla_started_at -= timedelta(hours=3)
        row.sla_deadline -= timedelta(hours=3)
        await db.commit()
    assert (await sla.scan_once())["breached"] == 1
    await wait_for(lambda: _is(t["id"], "ESCALATED"), what="automatic escalation by the SLA worker")
    assert (
        await count(
            ProcessedEvent, ProcessedEvent.consumer == "sla-worker", ProcessedEvent.event_type == "sla.breached"
        )
        == 1
    )
