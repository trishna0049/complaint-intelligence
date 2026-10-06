"""SLA engine: the clock maths (incl. the pause rule), policies, the SLA worker's handlers, the scanner's warning /
breach (once each), automatic escalation, queue filters, /sla-policies, /analytics/sla and the historical backfill."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.domain.sla import Clock, SlaState, pause, resume, retarget, stop, target_seconds
from app.models import AuditLog, OutboxEvent, ProcessedEvent, SlaEvent, SlaPolicy, Ticket
from app.services import sla

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
H = timedelta(hours=1)
M = timedelta(minutes=1)
PAYMENTS = {"description": "I was charged twice for my order of ₹12,500 and nobody helps", "channel": "Email"}


# ------------------------------------------------------------------------------------------------ maths (unit)
def test_running_clock():
    c = Clock(started_at=T0, target_seconds=7200)
    assert c.deadline(T0) == T0 + 2 * H and c.elapsed(T0 + 30 * M) == 1800 and c.remaining(T0 + 30 * M) == 5400
    assert c.state(T0 + 90 * M) is SlaState.RUNNING and not c.warning_due(T0 + 95 * M)
    assert c.warning_due(T0 + 96 * M) and c.state(T0 + 96 * M) is SlaState.AT_RISK  # 80 % of 120 min
    assert not c.breach_due(T0 + 119 * M) and c.breach_due(T0 + 2 * H) and c.state(T0 + 2 * H) is SlaState.BREACHED


def test_pause_rule_moves_the_deadline_by_the_time_spent_waiting():
    c = pause(Clock(started_at=T0, target_seconds=7200), T0 + 1 * H)
    assert c.state(T0 + 5 * H) is SlaState.PAUSED
    assert c.elapsed(T0 + 5 * H) == 3600  # the 4 paused hours don't count
    assert not c.warning_due(T0 + 5 * H) and not c.breach_due(T0 + 50 * H)  # a paused clock never fires
    assert c.deadline(T0 + 3 * H) == T0 + 4 * H  # keeps moving out while paused
    c = resume(c, T0 + 3 * H)  # waited 2 hours
    assert c.paused_seconds == 7200 and c.paused_since is None and c.deadline(T0 + 3 * H) == T0 + 4 * H
    assert c.elapsed(T0 + 3 * H + 30 * M) == 5400
    c = resume(pause(c, T0 + 3 * H + 30 * M), T0 + 3 * H + 45 * M)  # a second pause of 15 minutes adds up
    assert c.paused_seconds == 7200 + 900 and c.deadline(T0 + 4 * H) == T0 + 4 * H + 15 * M
    assert pause(pause(c, T0 + 5 * H), T0 + 6 * H).paused_since == T0 + 5 * H  # pausing twice is a no-op


def test_stop_met_or_breached_and_reopen_excludes_the_resolved_time():
    c = stop(Clock(started_at=T0, target_seconds=7200), T0 + 1 * H)
    assert c.state(T0 + 10 * H) is SlaState.MET and c.elapsed(T0 + 10 * H) == 3600  # stopped clocks don't run
    late = stop(Clock(started_at=T0, target_seconds=7200), T0 + 3 * H)
    assert late.state(T0 + 3 * H) is SlaState.BREACHED
    reopened = resume(c, T0 + 5 * H)  # resolved for 4 hours, then reopened
    assert reopened.stopped_at is None and reopened.elapsed(T0 + 5 * H + 30 * M) == 5400
    paused_then_resolved = stop(pause(Clock(started_at=T0, target_seconds=7200), T0 + 1 * H), T0 + 2 * H)
    assert paused_then_resolved.elapsed(T0 + 2 * H) == 3600 and paused_then_resolved.state(T0) is SlaState.MET


def test_retarget_and_demo_speedup():
    c = retarget(pause(Clock(started_at=T0, target_seconds=7200), T0 + 30 * M), 3600)
    assert c.target_seconds == 3600 and c.started_at == T0 and c.paused_since == T0 + 30 * M
    assert target_seconds(120, 1) == 7200 and target_seconds(120, 60) == 120 and target_seconds(1, 1000) == 1


# ------------------------------------------------------------------------------------------------ helpers
async def create(client, payload=PAYMENTS) -> dict:
    res = await client.post("/api/v1/tickets", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


async def shift(tid: int, delta: timedelta, *, paused: bool = False) -> None:
    """Move the clock back in time (as if `delta` had passed)."""
    async with SessionLocal() as db:
        t = await db.get(Ticket, tid)
        t.sla_started_at -= delta
        t.sla_deadline -= delta
        if paused and t.sla_paused_at:
            t.sla_paused_at -= delta
        await db.commit()


async def sla_events(tid: int) -> list[str]:
    async with SessionLocal() as db:
        rows = await db.scalars(select(SlaEvent.event_type).where(SlaEvent.ticket_id == tid).order_by(SlaEvent.id))
        return list(rows.all())


async def detail(client, tid: int) -> dict:
    return (await client.get(f"/api/v1/tickets/{tid}")).json()


# ------------------------------------------------------------------------------------------------ the engine
async def test_clock_starts_after_triage_with_the_priority_policy(client, org):
    t = await create(client)
    assert t["priority"] == "Critical"
    s = t["sla"]
    assert s["state"] == "running" and s["target_seconds"] == 7200 and s["policy"]["name"] == "Critical — 2 hours"
    started = datetime.fromisoformat(s["started_at"])
    assert started == datetime.fromisoformat(t["created_at"])  # the customer has waited since submission
    assert datetime.fromisoformat(s["deadline"]) == started + 2 * H and 7100 < s["remaining_seconds"] <= 7200
    assert await sla_events(t["id"]) == ["started"]
    assert next(e for e in t["timeline"] if e["event_type"] == "sla_started")["metadata"]["target_minutes"] == 120
    low = await create(client, {"description": "good service thank you"})
    assert low["sla"]["policy"]["name"] == "Low — 3 days"


async def test_a_category_specific_policy_wins(client, org):
    async with SessionLocal() as db:
        db.add(
            SlaPolicy(
                name="Payments critical — 1 hour", priority="Critical", category="Payments related", target_minutes=60
            )
        )
        await db.commit()
    t = await create(client)
    assert t["sla"]["policy"]["name"] == "Payments critical — 1 hour" and t["sla"]["target_seconds"] == 3600


async def test_waiting_on_the_customer_pauses_and_the_deadline_moves_out(client, agent_client, org):
    tid = (await create(client))["id"]
    await agent_client.patch(f"/api/v1/tickets/{tid}", json={"status": "IN_PROGRESS"})
    before = datetime.fromisoformat((await detail(client, tid))["sla"]["deadline"])
    await agent_client.patch(f"/api/v1/tickets/{tid}", json={"status": "WAITING_CUSTOMER"})
    d = await detail(client, tid)
    assert d["sla"]["state"] == "paused" and d["sla"]["paused"] is True
    async with SessionLocal() as db:  # the customer took 30 minutes to answer
        await db.execute(update(Ticket).where(Ticket.id == tid).values(sla_paused_at=Ticket.sla_paused_at - 30 * M))
        await db.commit()
    await agent_client.patch(f"/api/v1/tickets/{tid}", json={"status": "IN_PROGRESS"})
    d = await detail(client, tid)
    after = datetime.fromisoformat(d["sla"]["deadline"])
    assert d["sla"]["state"] == "running" and abs((after - before) - 30 * M) < timedelta(seconds=5)
    assert await sla_events(tid) == ["started", "paused", "resumed"]


async def test_warning_at_80_percent_and_breach_at_100_fire_once_and_escalate(client, org):
    tid = (await create(client))["id"]
    await shift(tid, 100 * M)  # 100 of 120 minutes used
    assert await sla.scan_once() == {"warning": 1, "breached": 0}
    assert await sla.scan_once() == {"warning": 0, "breached": 0}  # once
    d = await detail(client, tid)
    assert d["sla"]["state"] == "at_risk" and d["sla"]["warned_at"]
    assert any(e["event_type"] == "sla_warning" for e in d["timeline"])

    await shift(tid, 25 * M)  # now overdue
    assert await sla.scan_once() == {"warning": 0, "breached": 1}
    assert await sla.scan_once() == {"warning": 0, "breached": 0}
    d = await detail(client, tid)
    assert d["sla"]["state"] == "breached" and d["status"] == "ESCALATED"  # SLA worker escalated on sla.breached
    escalated = next(e for e in d["timeline"] if e["event_type"] == "escalated")
    assert escalated["actor"] is None and escalated["metadata"] == {
        "reason": "SLA breached (Critical — 2 hours)",
        "auto": True,
    }
    assert await sla_events(tid) == ["started", "warning", "breached"]
    async with SessionLocal() as db:
        types = (await db.scalars(select(OutboxEvent.event_type).where(OutboxEvent.ticket_id == tid))).all()
        handled = set((await db.execute(select(ProcessedEvent.consumer, ProcessedEvent.event_type))).all())
        audits = (await db.scalars(select(AuditLog.action))).all()
    assert types.count("sla.warning") == 1 and types.count("sla.breached") == 1 and "ticket.escalated" in types
    assert ("notification-worker", "sla.warning") in handled and ("sla-worker", "sla.breached") in handled
    assert "ticket.escalate" in audits


async def test_a_paused_clock_never_breaches(client, agent_client, org):
    tid = (await create(client))["id"]
    await agent_client.patch(f"/api/v1/tickets/{tid}", json={"status": "IN_PROGRESS"})
    await agent_client.patch(f"/api/v1/tickets/{tid}", json={"status": "WAITING_CUSTOMER"})
    # Even far beyond the deadline, a paused clock is never warned or breached by the scanner.
    assert await sla.scan_once(datetime.now(UTC) + 50 * H) == {"warning": 0, "breached": 0}
    assert (await detail(client, tid))["sla"]["state"] == "paused"


async def test_resolved_in_time_is_met_late_is_breached_and_reopen_resumes(client, agent_client, org):
    met = (await create(client))["id"]
    await agent_client.post(f"/api/v1/tickets/{met}/resolve", json={"resolution": "Refunded"})
    d = await detail(client, met)
    assert d["sla"]["state"] == "met" and (await sla_events(met))[-1] == "stopped"
    async with SessionLocal() as db:  # the clock is stopped: ten hours later it is still met
        t = await db.get(Ticket, met)
        assert sla.view(t, datetime.now(UTC) + 10 * H)["state"] == "met"
    assert await sla.scan_once(datetime.now(UTC) + 10 * H) == {"warning": 0, "breached": 0}
    await client.post(f"/api/v1/tickets/{met}/reopen", json={"reason": "Refund bounced"})
    d = await detail(client, met)
    assert d["sla"]["state"] in ("running", "breached") and (await sla_events(met))[-1] == "resumed"

    late = (await create(client))["id"]
    await shift(late, 3 * H)  # resolved after the deadline, before any scan
    await agent_client.post(f"/api/v1/tickets/{late}/resolve", json={"resolution": "Refunded late"})
    d = await detail(client, late)
    assert d["sla"]["state"] == "breached" and d["sla"]["breached_at"]


async def test_category_correction_retargets_the_clock(client, agent_client, org):
    tid = (await create(client))["id"]  # Critical: 2 hours
    body = (await agent_client.patch(f"/api/v1/tickets/{tid}", json={"category": "Feedback"})).json()
    d = await detail(client, tid)
    assert body["priority"] != "Critical" and d["sla"]["policy"]["name"] != "Critical — 2 hours"
    assert d["sla"]["target_seconds"] > 7200 and "retargeted" in await sla_events(tid)


async def test_demo_speedup(client, org, monkeypatch):
    monkeypatch.setattr(get_settings(), "sla_speedup", 60)
    t = await create(client)
    assert t["sla"]["target_seconds"] == 120  # a 2-hour SLA in 2 minutes


# ------------------------------------------------------------------------------------------------ API
async def test_policies_crud_is_admin_only_and_guards_the_defaults(client, agent_client, org):
    rows = (await client.get("/api/v1/sla-policies")).json()
    assert [(r["priority"], r["target_minutes"]) for r in rows] == [
        ("Critical", 120),
        ("High", 480),
        ("Medium", 1440),
        ("Low", 4320),
    ]
    assert (await agent_client.get("/api/v1/sla-policies")).status_code == 403
    body = {"name": "Refund high — 4 hours", "priority": "High", "category": "Refund Related", "target_minutes": 240}
    assert (await agent_client.post("/api/v1/sla-policies", json=body)).status_code == 403
    created = (await client.post("/api/v1/sla-policies", json=body)).json()
    assert created["category"] == "Refund Related"
    assert (await client.post("/api/v1/sla-policies", json=body)).status_code == 409
    assert (await client.post("/api/v1/sla-policies", json={**body, "category": "Nope"})).status_code == 422
    default_high = next(r for r in rows if r["priority"] == "High")
    res = await client.patch(f"/api/v1/sla-policies/{default_high['id']}", json={"target_minutes": 360})
    assert res.status_code == 200 and res.json()["target_minutes"] == 360
    assert (
        await client.patch(f"/api/v1/sla-policies/{default_high['id']}", json={"is_active": False})
    ).status_code == 409
    assert (await client.delete(f"/api/v1/sla-policies/{default_high['id']}")).status_code == 409
    assert (await client.delete(f"/api/v1/sla-policies/{created['id']}")).status_code == 204
    async with SessionLocal() as db:
        actions = (await db.scalars(select(AuditLog.action).where(AuditLog.action.like("sla_policy.%")))).all()
    assert actions == ["sla_policy.create", "sla_policy.update", "sla_policy.delete"]


async def test_queue_filters_and_due_soonest(client, agent_client, org):
    risky = (await create(client))["id"]
    late = (await create(client))["id"]
    calm = (await create(client, {"description": "good service thank you"}))["id"]
    await shift(risky, 100 * M)
    await shift(late, 3 * H)
    await sla.scan_once()
    q = lambda **p: client.get("/api/v1/tickets", params=p)  # noqa: E731
    assert [i["id"] for i in (await q(sla="at_risk")).json()["items"]] == [risky]
    assert {i["id"] for i in (await q(sla="breached")).json()["items"]} == {late}
    ordered = [i["id"] for i in (await q(sort="sla")).json()["items"]]
    assert ordered[:2] == [late, risky] and calm in ordered
    item = next(i for i in (await q()).json()["items"] if i["id"] == risky)
    assert item["sla"]["state"] == "at_risk" and item["sla"]["policy"]["target_minutes"] == 120


async def test_sla_analytics(client, agent_client, org):
    breached = (await create(client))["id"]
    await shift(breached, 3 * H)
    await sla.scan_once()
    met = (await create(client))["id"]
    await agent_client.post(f"/api/v1/tickets/{met}/resolve", json={"resolution": "done"})
    risky = (await create(client))["id"]
    await shift(risky, 100 * M)
    res = await client.get("/api/v1/analytics/sla", params={"days": 7})
    assert res.status_code == 200
    a = res.json()
    assert (
        a["with_sla"] == 3
        and a["breached"] == 1
        and a["met"] == 1
        and a["breach_rate"] == pytest.approx(1 / 3, abs=1e-3)
    )
    assert a["open"]["at_risk"] == 1 and a["open"]["breached"] == 1
    assert a["avg_target_minutes"] == 120 and a["by_priority"][0]["name"] == "Critical"
    assert a["by_team"][0]["name"] == "Payments Support" and a["trend"][-1]["with_sla"] == 3
    assert (await agent_client.get("/api/v1/analytics/sla")).status_code == 403


# ------------------------------------------------------------------------------------------------ migration backfill
async def test_history_gets_its_real_sla_outcome(org):
    """Migration 0009: imported (closed) tickets are scored against the default policy of their priority."""
    from alembic import command
    from alembic.config import Config

    from app.core.config import BACKEND_DIR

    from .conftest import TEST_DB

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["url"] = TEST_DB
    cfg.attributes["configure_logger"] = False
    await asyncio.to_thread(command.downgrade, cfg, "0008")
    try:
        async with SessionLocal() as db:
            from sqlalchemy import text

            await db.execute(
                text(
                    "INSERT INTO tickets (subject, description, source, description_source, channel, status, priority, "
                    "labels_from, needs_review, reopen_count, created_at, updated_at, resolved_at, closed_at) VALUES "
                    "('fast', 'x', 'dataset', 'template', 'Inbound', 'CLOSED', 'High', 'dataset', false, 0, "
                    " now() - interval '2 days', now(), now() - interval '2 days' + interval '1 hour', now()),"
                    "('slow', 'x', 'dataset', 'template', 'Inbound', 'CLOSED', 'High', 'dataset', false, 0, "
                    " now() - interval '2 days', now(), now() - interval '2 days' + interval '9 hours', now())"
                )
            )
            await db.commit()
    finally:
        await asyncio.to_thread(command.upgrade, cfg, "head")
    async with SessionLocal() as db:
        rows = dict((await db.execute(select(Ticket.subject, Ticket.sla_status))).all())
    assert rows == {"fast": "met", "slow": "breached"}  # High: 8 hours
