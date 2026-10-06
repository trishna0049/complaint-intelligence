"""Events (inline mode — same consumers as Kafka): the outbox written with each change, the event catalogue and
envelope, idempotency, retries, the dead-letter queue with Admin replay / discard, the LLM worker's auto-draft and
the asynchronous contract of ticket creation."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.events import bus
from app.events.consumer import Consumer, Outcome
from app.events.envelope import Envelope, EventType, all_topics, topic
from app.models import AuditLog, DeadLetter, OutboxEvent, ProcessedEvent, Ticket
from app.workers import registry

PAYMENTS = {"description": "I was charged twice for my order of ₹12,500 and nobody helps", "channel": "Email"}


async def outbox(ticket_id: int | None = None) -> list[OutboxEvent]:
    async with SessionLocal() as db:
        stmt = select(OutboxEvent).order_by(OutboxEvent.id)
        if ticket_id is not None:
            stmt = stmt.where(OutboxEvent.ticket_id == ticket_id)
        return list((await db.scalars(stmt)).all())


async def processed() -> set[tuple[str, str]]:
    async with SessionLocal() as db:
        return {(c, t) for c, t in (await db.execute(select(ProcessedEvent.consumer, ProcessedEvent.event_type))).all()}


async def create(client, payload=PAYMENTS) -> dict:
    res = await client.post("/api/v1/tickets", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


# ------------------------------------------------------------------------------------------------ catalogue
def test_event_catalogue_and_topics():
    assert [t.value for t in EventType] == [
        "ticket.created",
        "ai.analysis.completed",
        "ticket.assigned",
        "ticket.updated",
        "ticket.resolved",
        "ticket.escalated",
        "sla.warning",
        "sla.breached",
    ]
    assert topic(EventType.TICKET_CREATED) == "complaints.ticket.created"
    assert all_topics()[-1] == "complaints.dlq" and len(all_topics()) == 9
    subscriptions = {c.name: {t.value for t in c.event_types} for c in registry.CONSUMERS}
    assert subscriptions == {
        "ai-worker": {"ticket.created", "ticket.updated", "ticket.resolved"},
        "llm-worker": {"ai.analysis.completed"},
        "sla-worker": {"ai.analysis.completed", "ticket.updated", "ticket.resolved", "ticket.escalated"},
        "notification-worker": {"ticket.assigned", "ticket.escalated", "sla.warning", "sla.breached"},
    }


# ------------------------------------------------------------------------------------------------ the pipeline
async def test_creating_a_ticket_flows_through_the_workers(client, org):
    t = await create(client)
    assert t["status"] == "ASSIGNED" and t["category"] == "Payments related"  # inline: done before the response
    assert t["pipeline"] == {"triage": "done", "copilot": "manual"}
    rows = await outbox(t["id"])
    # Routing publishes ticket.assigned and, for the TRIAGED -> ASSIGNED status change, ticket.updated.
    assert [r.event_type for r in rows] == [
        "ticket.created",
        "ai.analysis.completed",
        "ticket.assigned",
        "ticket.updated",
    ]
    assert all(r.published_at is not None for r in rows)
    env = rows[0].envelope
    assert set(env) == {"event_id", "type", "timestamp", "ticket_id", "actor", "payload", "replay_of"}
    assert env["actor"] == {"id": org.admin.id, "name": "Ada Admin", "role": "ADMIN"}
    assert env["payload"]["ticket_number"] == t["ticket_number"] and env["payload"]["change"] == "created"
    assert rows[1].envelope["actor"]["id"] is None  # triage is the system's
    assert rows[2].envelope["payload"]["assignee_id"] == org.agent.id
    assert await processed() == {
        ("ai-worker", "ticket.created"),
        ("llm-worker", "ai.analysis.completed"),
        ("sla-worker", "ai.analysis.completed"),
        ("notification-worker", "ticket.assigned"),
        ("ai-worker", "ticket.updated"),
        ("sla-worker", "ticket.updated"),
    }


async def test_lifecycle_changes_publish_their_events(client, agent_client, org):
    tid = (await create(client))["id"]
    await agent_client.patch(f"/api/v1/tickets/{tid}", json={"status": "IN_PROGRESS"})
    await agent_client.post(f"/api/v1/tickets/{tid}/escalate", json={"reason": "Legal threat"})
    await agent_client.patch(f"/api/v1/tickets/{tid}", json={"category": "Refund Related"})
    await agent_client.post(f"/api/v1/tickets/{tid}/resolve", json={"resolution": "Refunded"})
    await client.post(f"/api/v1/tickets/{tid}/comments", json={"body": "no event for comments"})
    types = [r.event_type for r in await outbox(tid)][4:]  # after created, analysis, assigned + updated
    assert types == [
        "ticket.updated",  # ASSIGNED -> IN_PROGRESS
        "ticket.updated",  # -> ESCALATED (status change)
        "ticket.escalated",
        "ticket.updated",  # category corrected
        "ticket.resolved",
    ]
    assert ("notification-worker", "ticket.escalated") in await processed()
    assert ("ai-worker", "ticket.resolved") in await processed()


async def test_events_are_written_in_the_same_transaction_as_the_change(client, org, monkeypatch):
    tid = (await create(client))["id"]
    before = len(await outbox())
    from app.services import tickets as svc

    async def boom(db):
        await db.flush()
        raise RuntimeError("database went away")

    monkeypatch.setattr(svc, "commit", boom)
    with pytest.raises(RuntimeError):
        await client.post(f"/api/v1/tickets/{tid}/escalate", json={"reason": "angry"})
    assert len(await outbox()) == before  # rolled back with the change: nothing published for it


async def test_kafka_mode_returns_new_at_once_and_workers_finish_later(client, org, monkeypatch):
    monkeypatch.setattr(get_settings(), "events_mode", "kafka")
    t = await create(client)
    assert t["status"] == "NEW" and t["category"] is None and t["pipeline"]["triage"] == "pending"
    assert t["assignee"] is None and [e["event_type"] for e in t["timeline"]] == ["created"]
    (row,) = await outbox(t["id"])
    assert row.event_type == "ticket.created" and row.published_at is None  # waiting for the relay
    monkeypatch.setattr(get_settings(), "events_mode", "inline")
    await bus.drain()  # what relay + workers do
    detail = (await client.get(f"/api/v1/tickets/{t['id']}")).json()
    assert detail["status"] == "ASSIGNED" and detail["pipeline"]["triage"] == "done"
    assert detail["order_id"] is None and detail["amount_inr"] == 12500  # filled from the extracted entities


# ------------------------------------------------------------------------------------------------ framework
def envelope(**kw: Any) -> Envelope:
    return Envelope(type=EventType.TICKET_UPDATED, ticket_id=None, **kw)


async def test_idempotency_each_event_is_handled_once_per_consumer(org):
    calls: list[uuid.UUID] = []

    async def handler(db, env):
        calls.append(env.event_id)

    c = Consumer("test-consumer", {EventType.TICKET_UPDATED: handler})
    env = envelope()
    assert await c.process(env) is Outcome.PROCESSED
    assert await c.process(env) is Outcome.DUPLICATE  # redelivery
    assert await c.process(envelope()) is Outcome.PROCESSED  # a different event
    assert len(calls) == 2
    other = Consumer("other-consumer", {EventType.TICKET_UPDATED: handler})
    assert await other.process(env) is Outcome.PROCESSED  # idempotency is per consumer
    assert await Consumer("x", {}).process(env) is Outcome.IGNORED


async def test_handler_writes_and_the_idempotency_record_commit_together(org):
    async def half_done(db, env):
        db.add(Ticket(subject="side effect", description="should roll back", status="NEW"))
        await db.flush()
        raise RuntimeError("crash after writing")

    c = Consumer("atomic-consumer", {EventType.TICKET_UPDATED: half_done})
    assert await c.process(envelope()) is Outcome.DEAD_LETTERED
    async with SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(Ticket)) == 0
        assert await db.scalar(select(func.count()).select_from(ProcessedEvent)) == 0


async def test_retries_then_success(org):
    attempts = {"n": 0}

    async def flaky(db, env):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionError("provider hiccup")

    assert await Consumer("flaky", {EventType.TICKET_UPDATED: flaky}).process(envelope()) is Outcome.PROCESSED
    assert attempts["n"] == 3
    async with SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(DeadLetter)) == 0


async def test_after_three_retries_the_event_waits_in_the_dlq(client, agent_client, org):
    attempts = {"n": 0}

    async def broken(db, env):
        attempts["n"] += 1
        raise ValueError("bad data")

    env = envelope(payload={"x": 1})
    published: list[DeadLetter] = []

    async def dlq(letter):
        published.append(letter)

    assert await Consumer("broken", {EventType.TICKET_UPDATED: broken}).process(env, dlq=dlq) is Outcome.DEAD_LETTERED
    assert attempts["n"] == 4  # 1 try + 3 retries
    (letter,) = published
    assert letter.attempts == 4 and letter.status == "waiting" and letter.error == "ValueError: bad data"
    page = (await client.get("/api/v1/admin/dlq")).json()
    assert page["total"] == 1 and page["items"][0]["event_id"] == str(env.event_id)
    assert page["items"][0]["envelope"]["payload"] == {"x": 1}
    assert (await agent_client.get("/api/v1/admin/dlq")).status_code == 403
    assert (await agent_client.post(f"/api/v1/admin/dlq/{letter.id}/replay")).status_code == 403


async def test_admin_replay_reprocesses_only_the_failed_consumer(client, org, monkeypatch):
    fixed = {"value": False}
    handled: list[str] = []

    async def sometimes(db, env):
        if not fixed["value"]:
            raise RuntimeError("downstream down")
        handled.append("failed-consumer")

    async def fine(db, env):
        handled.append("healthy-consumer")

    failing = Consumer("failed-consumer", {EventType.TICKET_UPDATED: sometimes})
    healthy = Consumer("healthy-consumer", {EventType.TICKET_UPDATED: fine})
    monkeypatch.setattr(registry, "CONSUMERS", [failing, healthy])
    tid = (await create(client, {"description": "general question about something"}))["id"]
    await client.patch(f"/api/v1/tickets/{tid}", json={"category": "Returns"})  # -> ticket.updated
    assert handled == ["healthy-consumer"]
    (letter,) = (await client.get("/api/v1/admin/dlq")).json()["items"]
    assert letter["consumer"] == "failed-consumer" and letter["ticket_id"] == tid

    fixed["value"] = True
    res = await client.post(f"/api/v1/admin/dlq/{letter['id']}/replay")
    assert res.status_code == 200 and res.json()["status"] == "replayed" and res.json()["resolved_by_id"]
    assert handled == ["healthy-consumer", "failed-consumer"]  # healthy one skipped the replay as a duplicate
    replays = [r for r in await outbox(tid) if r.envelope.get("replay_of") == letter["id"]]
    assert len(replays) == 1 and str(replays[0].event_id) == letter["event_id"]
    assert (await client.post(f"/api/v1/admin/dlq/{letter['id']}/replay")).status_code == 409
    assert (await client.get("/api/v1/admin/dlq")).json()["total"] == 0
    assert (await client.get("/api/v1/admin/dlq", params={"status": "replayed"})).json()["total"] == 1
    async with SessionLocal() as db:
        assert "dlq.replay" in (await db.scalars(select(AuditLog.action))).all()


async def test_discard(client, org):
    async def broken(db, env):
        raise ValueError("never works")

    await Consumer("broken", {EventType.TICKET_UPDATED: broken}).process(envelope())
    (letter,) = (await client.get("/api/v1/admin/dlq")).json()["items"]
    res = await client.post(f"/api/v1/admin/dlq/{letter['id']}/discard", json={"reason": "obsolete"})
    assert res.status_code == 200 and res.json()["status"] == "discarded"
    assert (await client.post(f"/api/v1/admin/dlq/{letter['id']}/discard", json={})).status_code == 409
    assert (await client.post("/api/v1/admin/dlq/999/replay")).status_code == 404


async def test_pipeline_status(client, agent_client, org):
    await create(client)
    status = (await client.get("/api/v1/admin/events")).json()
    assert status["mode"] == "inline" and status["retries"] == 3 and status["outbox"]["pending"] == 0
    by_name = {c["name"]: c for c in status["consumers"]}
    assert by_name["ai-worker"]["processed_total"] == 2  # ticket.created + ticket.updated (routing)
    assert by_name["ai-worker"]["processed_last_hour"] == 2
    assert by_name["llm-worker"]["events"] == ["ai.analysis.completed"]
    assert (await agent_client.get("/api/v1/admin/events")).status_code == 403


# ------------------------------------------------------------------------------------------------ LLM worker
async def test_llm_worker_drafts_the_copilot_answer_after_triage(client, agent_client, org, monkeypatch):
    monkeypatch.setattr(get_settings(), "copilot_auto", True)
    t = await create(client)
    cp = t["copilot"]
    assert cp and cp["draft_status"] == "pending" and cp["root_cause"] and t["pipeline"]["copilot"] == "ready"
    event = next(e for e in t["timeline"] if e["event_type"] == "copilot_generated")
    assert event["actor"] is None and event["metadata"]["auto"] is True
    # Redelivery of ai.analysis.completed must not draft twice.
    async with SessionLocal() as db:
        row = await db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "ai.analysis.completed"))
    assert await registry.BY_NAME["llm-worker"].process(Envelope.model_validate(row.envelope)) is Outcome.DUPLICATE
    detail = (await agent_client.get(f"/api/v1/tickets/{t['id']}")).json()
    assert [e["event_type"] for e in detail["timeline"]].count("copilot_generated") == 1


async def test_llm_outage_dead_letters_then_replay_drafts(client, org, monkeypatch):
    from app.ai import llm

    monkeypatch.setattr(get_settings(), "copilot_auto", True)
    real = llm.MockProvider.generate
    down = {"value": True}

    def flaky(self, text, context):  # type: ignore[no-untyped-def]
        if down["value"]:
            raise llm.LLMError("llm_rate_limited", "rate limited", 429)
        return real(self, text, context)

    monkeypatch.setattr(llm.MockProvider, "generate", flaky)
    t = await create(client)
    assert t["copilot"] is None and t["pipeline"] == {"triage": "done", "copilot": "failed"}
    (letter,) = (await client.get("/api/v1/admin/dlq")).json()["items"]
    assert letter["consumer"] == "llm-worker" and "rate limited" in letter["error"] and letter["attempts"] == 4
    down["value"] = False
    await client.post(f"/api/v1/admin/dlq/{letter['id']}/replay")
    detail = (await client.get(f"/api/v1/tickets/{t['id']}")).json()
    assert detail["copilot"]["draft_status"] == "pending" and detail["pipeline"]["copilot"] == "ready"
