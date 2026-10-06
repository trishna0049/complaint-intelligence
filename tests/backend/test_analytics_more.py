"""Analytics completion: first-response / resolution times, the repeat-complaint rate, rates by channel / city /
product with data coverage, team and agent workload, "My stats", operational insights, and the history tools
(score_history, backfill_history)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Ticket
from app.services import sla
from scripts import backfill_history

PAYMENTS = {"description": "I was charged twice for my order of ₹12,500 and nobody helps", "channel": "Email"}
NOW = datetime.now(UTC)


async def history(**kw) -> Ticket:
    """An imported (closed) dataset ticket."""
    created = kw.pop("created", NOW - timedelta(days=2))
    minutes = kw.pop("minutes", 10)
    async with SessionLocal() as db:
        t = Ticket(
            subject=kw.pop("subject", "Delayed — Order Related"),
            description=kw.pop("description", "Where is my order, it is late"),
            source="dataset",
            description_source=kw.pop("description_source", "dataset_remark"),
            channel=kw.pop("channel", "Inbound"),
            status="CLOSED",
            priority=kw.pop("priority", "Medium"),
            category=kw.pop("category", "Order Related"),
            created_at=created,
            first_response_at=created + timedelta(minutes=minutes),
            resolved_at=created + timedelta(minutes=minutes),
            closed_at=created + timedelta(minutes=minutes),
            **kw,
        )
        db.add(t)
        await db.commit()
        return t


async def test_response_and_resolution_times(client, agent_client, org):
    for m in (5, 10, 60, 600):
        await history(minutes=m)
    await history(minutes=30, channel="Email")
    tid = (await client.post("/api/v1/tickets", json=PAYMENTS)).json()["id"]  # open: no resolution yet
    await agent_client.post(f"/api/v1/tickets/{tid}/comments", json={"body": "On it"})  # its first response
    res = await client.get("/api/v1/analytics/performance", params={"days": 7})
    assert res.status_code == 200
    p = res.json()
    assert p["tickets"] == 6
    fr, rs = p["first_response"], p["resolution"]
    assert fr["count"] == 6 and rs["count"] == 5 and rs["coverage"] == pytest.approx(5 / 6, abs=1e-3)
    assert rs["median_minutes"] == 30 and rs["avg_minutes"] == pytest.approx((5 + 10 + 60 + 600 + 30) / 5, abs=0.1)
    assert fr["p90_minutes"] >= 60
    email = next(c for c in p["by_channel"] if c["name"] == "Email")
    assert email["tickets"] == 2 and email["median_resolution_minutes"] == 30
    assert p["trend"] and sum(x["tickets"] for x in p["trend"]) == 6
    weekly = (await client.get("/api/v1/analytics/performance", params={"days": 30, "granularity": "week"})).json()
    assert weekly["granularity"] == "week"
    assert (await agent_client.get("/api/v1/analytics/performance")).status_code == 403


async def test_repeat_complaint_rate(client, org):
    await client.post("/api/v1/tickets", json={**PAYMENTS, "customer_name": "Ravi Kumar"})
    await client.post(
        "/api/v1/tickets", json={"description": "refund still not credited", "customer_code": "CUS-00001"}
    )
    await client.post("/api/v1/tickets", json={"description": "I have contacted you three times about this order"})
    await client.post("/api/v1/tickets", json={"description": "first time asking about delivery"})
    r = (await client.get("/api/v1/analytics/performance", params={"days": 7})).json()["repeat"]
    assert r["known_customer"] == 2 and r["returning_customer"] == 1  # Ravi's second ticket
    assert r["repeat_cue"] >= 1 and r["repeats"] >= 2 and 0 < r["repeat_rate"] <= 1


async def test_rates_by_channel_city_and_product_report_their_coverage(client, org):
    await history(city="Pune", product="Mobile")
    await history(city="Pune")
    await history()
    await history(channel="Email")
    cats = (await client.get("/api/v1/analytics/categories", params={"days": 7})).json()
    city = cats["city_rates"]
    assert city["coverage"] == 0.5 and city["with_value"] == 2 and city["items"][0]["name"] == "Pune"
    assert cats["product_rates"]["coverage"] == 0.25
    pune = city["items"][0]
    assert pune["breach_rate"] is None  # no SLA clock on these rows
    channels = {c["name"]: c for c in cats["channel_rates"]["items"]}
    assert channels["Inbound"]["count"] == 3 and cats["channel_rates"]["coverage"] == 1


async def test_workload_by_team_and_agent(client, agent_client, org):
    await client.post("/api/v1/tickets", json=PAYMENTS)  # Arjun
    await client.post("/api/v1/tickets", json=PAYMENTS)  # Arjun (only agent of the team)
    await client.post("/api/v1/tickets", json={"description": "refund not received yet, where is my refund"})  # queue
    w = (await client.get("/api/v1/analytics/workload")).json()
    teams = {t["team"]: t for t in w["teams"]}
    pay = teams["Payments Support"]
    assert pay["open"] == 2 and pay["agents"] == 1 and pay["open_per_agent"] == 2 and pay["created_7d"] == 2
    refunds = next(t for t in w["teams"] if t["unassigned"] == 1)
    assert refunds["agents"] == 0 and refunds["open_per_agent"] is None
    assert w["agents"][0]["name"] == "Arjun Agent" and w["agents"][0]["open"] == 2
    assert w["totals"]["open"] == 3 and w["totals"]["unassigned"] == 1
    assert (await agent_client.get("/api/v1/analytics/workload")).status_code == 403


async def test_my_stats(client, agent_client, other_agent_client, org):
    a = (await client.post("/api/v1/tickets", json=PAYMENTS)).json()["id"]
    b = (await client.post("/api/v1/tickets", json=PAYMENTS)).json()["id"]
    await agent_client.post(f"/api/v1/tickets/{a}/resolve", json={"resolution": "Refunded"})
    async with SessionLocal() as db:  # make b at risk (100 of 120 minutes used)
        t = await db.get(Ticket, b)
        t.sla_started_at -= timedelta(minutes=100)
        t.sla_deadline -= timedelta(minutes=100)
        await db.commit()
    me = (await agent_client.get("/api/v1/analytics/me")).json()
    assert me["open"] == 1 and me["sla_at_risk"] == 1 and me["resolved_this_week"] == 1
    assert me["sla_met_rate_this_week"] == 1 and me["median_resolution_minutes_this_week"] is not None
    assert me["team_unassigned"] == 0
    other = (await other_agent_client.get("/api/v1/analytics/me")).json()
    assert other["open"] == 0 and other["resolved_this_week"] == 0
    assert (await client.get("/api/v1/analytics/me")).status_code == 200  # admins have their own stats too


async def test_operational_insights_name_the_worst_team_and_backlog(client, org):
    for _ in range(3):
        await client.post("/api/v1/tickets", json={"description": "refund not received yet, where is my refund"})
    notes = (await client.get("/api/v1/analytics/overview", params={"days": 7})).json()["insights"]
    assert any("largest unassigned backlog: 3 open tickets" in n for n in notes)


# ------------------------------------------------------------------------------------------------ history tools
async def test_score_history_is_idempotent(org):
    fast = await history(priority="High", minutes=60)
    slow = await history(priority="High", minutes=9 * 60)
    async with SessionLocal() as db:
        assert await sla.score_history(db) == 2
        await db.commit()
        assert await sla.score_history(db) == 0
        rows = dict((await db.execute(select(Ticket.id, Ticket.sla_status))).all())
    assert rows == {fast.id: "met", slow.id: "breached"}


async def test_backfill_adds_entities_raises_repeat_priority_and_rescoring(org):
    t = await history(
        description="I have contacted you three times already and still no refund",
        priority="Low",
        category="Others",
        minutes=10,
    )
    plain = await history(description="good service", minutes=10)
    async with SessionLocal() as db:
        await sla.score_history(db)
        await db.commit()
    counts = await backfill_history.run()
    assert counts == {"entities": 2, "repriced": 1, "sla_scored": 1}
    assert await backfill_history.run() == {"entities": 0, "repriced": 0, "sla_scored": 0}
    async with SessionLocal() as db:
        t2, p2 = await db.get(Ticket, t.id), await db.get(Ticket, plain.id)
    assert t2.entities["repeat_contact"] is True and t2.priority == "Medium"  # R5: repeat contact raises priority
    assert any(r["rule"] == "R5" for r in t2.priority_reasons)
    assert t2.sla_status == "met" and t2.sla_target_seconds == 1440 * 60  # re-scored against Medium
    assert p2.entities["repeat_contact"] is False and p2.priority == "Medium"
