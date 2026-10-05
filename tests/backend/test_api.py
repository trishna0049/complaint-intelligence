from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.db import SessionLocal
from app.models import Ticket

SPEC_EXAMPLE = {
    "subject": "Charged twice",
    "description": "I was charged twice for my order of ₹12,500 and have already contacted support three times. "
    "This is the worst, I am furious.",
    "channel": "Email",
    "customer_name": "Ravi Kumar",
}


async def test_health(client):
    body = (await client.get("/api/v1/health")).json()
    assert body["status"] == "ok" and body["classifier"] == "test-tiny" and body["llm_provider"] == "mock"


async def test_old_unversioned_routes_are_gone(client):
    assert (await client.get("/api/complaints")).status_code == 404
    assert (await client.get("/api/dashboard")).status_code == 404


async def test_create_ticket_runs_full_triage(client):
    res = await client.post("/api/v1/tickets", json=SPEC_EXAMPLE)
    assert res.status_code == 201, res.text
    t = res.json()
    assert t["ticket_number"] == "INC-00001"
    assert t["category"] == "Payments related"
    assert t["sentiment"] in ("Very Negative", "Negative")
    assert t["priority"] == "Critical"
    assert t["amount_inr"] == 12500
    assert t["entities"]["repeat_contact"] is True
    assert t["priority_reasons"][0]["rule"] == "BASE"
    assert t["labels_from"] == "model" and t["model_version"].startswith("test-tiny")
    assert t["description_source"] == "customer"
    assert 0 <= t["category_confidence"] <= 1
    assert t["intent"] in ("Online Payment Issues", "Payment related Queries")  # consistent with category
    assert t["copilot"] is None


async def test_ticket_numbers_pad_to_five_digits_and_grow():
    async with SessionLocal() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT setval('ticket_number_seq', 99998)"))
        numbers = [(await db.execute(text("SELECT next_ticket_number()"))).scalar() for _ in range(3)]
    assert numbers == ["INC-99999", "INC-100000", "INC-100001"]


async def test_every_triage_is_recorded_as_an_analysis(client):
    tid = (await client.post("/api/v1/tickets", json=SPEC_EXAMPLE)).json()["id"]
    async with SessionLocal() as db:
        t = await db.get(Ticket, tid)
        assert [a.kind for a in t.analyses] == ["triage"]
        a = t.analyses[0]
        assert (a.category, a.priority, a.model_version) == (t.category, t.priority, t.model_version)
        assert a.confidence == t.category_confidence


async def test_analyze_preview_does_not_save(client):
    res = await client.post("/api/v1/ai/analyze", json={"description": "refund not received for my return"})
    assert res.status_code == 200 and res.json()["category"] == "Refund Related"
    assert (await client.get("/api/v1/tickets")).json()["total"] == 0


async def test_validation(client):
    assert (await client.post("/api/v1/tickets", json={"description": "   "})).status_code == 422
    bad = {"description": "valid text here", "amount_inr": -1}
    assert (await client.post("/api/v1/tickets", json=bad)).status_code == 422
    bad = {"description": "valid text here", "channel": "Fax"}
    assert (await client.post("/api/v1/tickets", json=bad)).status_code == 422


async def test_list_filters_search_and_pagination(client):
    for text in [
        "payment failed money deducted",
        "refund not received yet",
        "order delayed not delivered",
        "return pickup not done",
        "upi payment pending twice",
    ]:
        await client.post("/api/v1/tickets", json={"description": text})
    all_ = (await client.get("/api/v1/tickets")).json()
    assert all_["total"] == 5
    assert (await client.get("/api/v1/tickets", params={"q": "refund"})).json()["total"] == 1
    found = (await client.get("/api/v1/tickets", params={"q": "inc-00002"})).json()
    assert found["items"][0]["ticket_number"] == "INC-00002"
    payments = (await client.get("/api/v1/tickets", params={"category": "Payments related"})).json()
    assert payments["total"] == 2
    page2 = (await client.get("/api/v1/tickets", params={"page": 2, "page_size": 2})).json()
    assert len(page2["items"]) == 2 and page2["page"] == 2
    by_priority = (await client.get("/api/v1/tickets", params={"sort": "priority"})).json()["items"]
    order = ["Low", "Medium", "High", "Critical"]
    ranks = [order.index(i["priority"]) for i in by_priority]
    assert ranks == sorted(ranks, reverse=True)
    assert (await client.get("/api/v1/tickets", params={"sort": "bogus"})).status_code == 422


async def test_category_correction_recomputes_priority(client):
    tid = (await client.post("/api/v1/tickets", json={"description": "hello there general question"})).json()["id"]
    res = await client.patch(f"/api/v1/tickets/{tid}", json={"category": "Refund Related"})
    body = res.json()
    assert body["category"] == "Refund Related" and body["labels_from"] == "human" and body["needs_review"] is False
    assert body["priority"] in ("High", "Critical")  # Refund base priority is High
    assert body["timeline"][-1]["event_type"] == "category_corrected"
    assert (await client.patch(f"/api/v1/tickets/{tid}", json={"category": "Nope"})).status_code == 422
    assert (await client.get("/api/v1/tickets/9999")).status_code == 404


async def test_copilot_draft_response_with_mock_llm(client):
    tid = (await client.post("/api/v1/tickets", json=SPEC_EXAMPLE)).json()["id"]
    res = await client.post("/api/v1/ai/draft-response", json={"ticket_id": tid})
    assert res.status_code == 201
    a = res.json()
    assert a["kind"] == "copilot" and a["provider"] == "mock" and a["prompt_version"] == "insight-v1"
    assert a["summary"] and a["key_issues"] and a["recommendations"] and a["draft_response"]
    assert a["category"] == "Payments related" and a["model_version"].startswith("test-tiny")
    assert "Ravi Kumar" not in a["summary"]  # customer name masked before the LLM
    detail = (await client.get(f"/api/v1/tickets/{tid}")).json()
    assert detail["copilot"]["id"] == a["id"]
    assert (await client.post("/api/v1/ai/draft-response", json={"ticket_id": 999})).status_code == 404


async def seed_refund_history() -> None:
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        rows = []
        # 30 refund tickets this week, 20 last week -> +50% emerging issue
        for i in range(30):
            rows.append(
                Ticket(
                    subject="s",
                    description="t",
                    category="Refund Related",
                    intent="Refund Enquiry",
                    sentiment="Negative",
                    priority="High",
                    status="IN_PROGRESS",
                    csat_score=2,
                    created_at=now - timedelta(days=1, minutes=i),
                )
            )
        for i in range(20):
            rows.append(
                Ticket(
                    subject="s",
                    description="t",
                    category="Refund Related",
                    intent="Refund Enquiry",
                    sentiment="Positive",
                    priority="Medium",
                    status="CLOSED",
                    csat_score=5,
                    created_at=now - timedelta(days=9, minutes=i),
                )
            )
        db.add_all(rows)
        await db.commit()


async def test_analytics_overview_categories_trends_emerging(client):
    await seed_refund_history()
    o = (await client.get("/api/v1/analytics/overview", params={"days": 30})).json()
    k = o["kpis"]
    assert k["total"] == 50 and k["open"] == 30 and k["high_priority"] == 30
    assert k["negative_share"] == 0.6
    assert any("Refund Related complaints rose 50%" in s for s in o["insights"])
    assert len(o["high_priority_open"]) == 8 and o["high_priority_open"][0]["ticket_number"].startswith("INC-")

    c = (await client.get("/api/v1/analytics/categories", params={"days": 30})).json()
    assert c["categories"][0] == {"name": "Refund Related", "count": 50, "negative_share": 0.6, "high_priority": 30}
    assert c["intents"][0]["name"] == "Refund Enquiry"
    assert {s["name"]: s["count"] for s in c["sentiment"]}["Negative"] == 30

    day = (await client.get("/api/v1/analytics/trends", params={"days": 30})).json()
    assert day["granularity"] == "day" and sum(p["total"] for p in day["points"]) == 50
    week = (await client.get("/api/v1/analytics/trends", params={"days": 30, "granularity": "week"})).json()
    assert sum(p["total"] for p in week["points"]) == 50 and len(week["points"]) <= 3
    month = (await client.get("/api/v1/analytics/trends", params={"days": 30, "granularity": "month"})).json()
    assert sum(p["total"] for p in month["points"]) == 50 and len(month["points"]) <= 2
    bad = await client.get("/api/v1/analytics/trends", params={"granularity": "hour"})
    assert bad.status_code == 422

    e = (await client.get("/api/v1/analytics/emerging")).json()["emerging"]
    assert e[0]["category"] == "Refund Related" and e[0]["change_pct"] == 50.0


async def test_analytics_is_cached_and_invalidated_by_writes(client):
    await client.post("/api/v1/tickets", json={"description": "refund not received yet"})
    assert (await client.get("/api/v1/analytics/overview", params={"days": 7})).json()["kpis"]["total"] == 1
    # A write invalidates the Redis cache, so the next read sees the new ticket.
    await client.post("/api/v1/tickets", json={"description": "order delayed not delivered"})
    assert (await client.get("/api/v1/analytics/overview", params={"days": 7})).json()["kpis"]["total"] == 2


async def test_cache_keys_are_namespaced_by_database(client):
    """Two databases sharing one Redis (dev and e2e) must never read each other's cached analytics."""
    from app.core.config import get_settings
    from app.core.redis import cached_json, get_redis

    calls = []

    async def compute():
        calls.append(1)
        return {"n": len(calls)}

    assert await cached_json("t", "k", 60, compute) == {"n": 1}
    assert await cached_json("t", "k", 60, compute) == {"n": 1}  # served from Redis
    keys = [k async for k in get_redis().scan_iter("cache:*:t:*")]
    assert keys and all(k.startswith("cache:complaints_test:") for k in keys)
    original = get_settings().database_url
    try:
        get_settings().database_url = original.rsplit("/", 1)[0] + "/other_db_test"
        assert await cached_json("t", "k", 60, compute) == {"n": 2}  # different database → not shared
    finally:
        get_settings().database_url = original


async def test_overview_hides_change_when_previous_period_has_no_data(client):
    await client.post("/api/v1/tickets", json={"description": "refund not received yet"})
    k = (await client.get("/api/v1/analytics/overview", params={"days": 7})).json()["kpis"]
    assert k["total"] == 1 and k["total_change_pct"] is None


def test_import_day_shift_lands_newest_record_yesterday():
    from scripts.import_dataset import day_shift

    latest = datetime(2023, 8, 31, 23, 58, tzinfo=UTC)
    now = datetime(2026, 10, 4, 0, 30, tzinfo=UTC)
    shifted = latest + day_shift(latest, now)
    assert shifted.date() == datetime(2026, 10, 3).date() and shifted < now
