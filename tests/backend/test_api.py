from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.db import SessionLocal
from app.models import Complaint

SPEC_EXAMPLE = {
    "subject": "Charged twice",
    "text": "I was charged twice for my order of ₹12,500 and have already contacted support three times. "
    "This is the worst, I am furious.",
    "channel": "Email",
    "customer_name": "Ravi Kumar",
}


async def test_health(client):
    body = (await client.get("/api/health")).json()
    assert body["status"] == "ok" and body["classifier"] == "test-tiny" and body["llm_provider"] == "mock"


async def test_create_complaint_runs_full_triage(client):
    res = await client.post("/api/complaints", json=SPEC_EXAMPLE)
    assert res.status_code == 201, res.text
    c = res.json()
    assert c["reference"] == "CMP-000001"
    assert c["category"] == "Payments related"
    assert c["sentiment"] in ("Very Negative", "Negative")
    assert c["priority"] == "Critical"
    assert c["amount_inr"] == 12500
    assert c["entities"]["repeat_contact"] is True
    assert c["priority_reasons"][0]["rule"] == "BASE"
    assert c["labels_from"] == "model" and c["model_version"].startswith("test-tiny")
    assert 0 <= c["category_confidence"] <= 1
    assert c["intent"] in ("Online Payment Issues", "Payment related Queries")  # consistent with category


async def test_triage_preview_does_not_save(client):
    res = await client.post("/api/triage", json={"text": "refund not received for my return"})
    assert res.status_code == 200 and res.json()["category"] == "Refund Related"
    assert (await client.get("/api/complaints")).json()["total"] == 0


async def test_validation(client):
    assert (await client.post("/api/complaints", json={"text": "   "})).status_code == 422
    assert (await client.post("/api/complaints", json={"text": "valid text here", "amount_inr": -1})).status_code == 422
    assert (await client.post("/api/complaints", json={"text": "valid text here", "channel": "Fax"})).status_code == 422


async def test_list_filters_search_and_pagination(client):
    for text in [
        "payment failed money deducted",
        "refund not received yet",
        "order delayed not delivered",
        "return pickup not done",
        "upi payment pending twice",
    ]:
        await client.post("/api/complaints", json={"text": text})
    all_ = (await client.get("/api/complaints")).json()
    assert all_["total"] == 5
    assert (await client.get("/api/complaints", params={"q": "refund"})).json()["total"] == 1
    found = (await client.get("/api/complaints", params={"q": "CMP-000002"})).json()
    assert found["items"][0]["reference"] == "CMP-000002"
    payments = (await client.get("/api/complaints", params={"category": "Payments related"})).json()
    assert payments["total"] == 2
    page2 = (await client.get("/api/complaints", params={"page": 2, "page_size": 2})).json()
    assert len(page2["items"]) == 2 and page2["page"] == 2
    by_priority = (await client.get("/api/complaints", params={"sort": "priority"})).json()["items"]
    order = ["Low", "Medium", "High", "Critical"]
    ranks = [order.index(i["priority"]) for i in by_priority]
    assert ranks == sorted(ranks, reverse=True)
    assert (await client.get("/api/complaints", params={"sort": "bogus"})).status_code == 422


async def test_update_status_and_category_correction(client):
    cid = (await client.post("/api/complaints", json={"text": "hello there general question"})).json()["id"]
    res = await client.patch(f"/api/complaints/{cid}", json={"status": "Resolved"})
    assert res.json()["status"] == "Resolved" and res.json()["resolved_at"]
    res = await client.patch(f"/api/complaints/{cid}", json={"category": "Refund Related"})
    body = res.json()
    assert body["category"] == "Refund Related" and body["labels_from"] == "human" and body["needs_review"] is False
    assert body["priority"] in ("High", "Critical")  # Refund base priority is High
    assert (await client.patch(f"/api/complaints/{cid}", json={"category": "Nope"})).status_code == 422
    assert (await client.get("/api/complaints/9999")).status_code == 404


async def test_generate_insights_with_mock_llm(client):
    cid = (await client.post("/api/complaints", json=SPEC_EXAMPLE)).json()["id"]
    res = await client.post(f"/api/complaints/{cid}/insights")
    assert res.status_code == 201
    ins = res.json()
    assert ins["provider"] == "mock" and ins["prompt_version"] == "insight-v1"
    assert ins["summary"] and ins["key_issues"] and ins["recommended_actions"]
    assert "Ravi Kumar" not in ins["summary"]  # customer name masked before the LLM
    detail = (await client.get(f"/api/complaints/{cid}")).json()
    assert detail["insight"]["id"] == ins["id"]


async def test_dashboard_aggregates(client):
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        rows = []
        # 30 refund complaints this week, 20 last week -> +50% emerging issue
        for i in range(30):
            rows.append(
                Complaint(
                    subject="s",
                    text="t",
                    category="Refund Related",
                    sentiment="Negative",
                    priority="High",
                    status="Open",
                    csat_score=2,
                    created_at=now - timedelta(days=1, minutes=i),
                )
            )
        for i in range(20):
            rows.append(
                Complaint(
                    subject="s",
                    text="t",
                    category="Refund Related",
                    sentiment="Positive",
                    priority="Medium",
                    status="Resolved",
                    csat_score=5,
                    created_at=now - timedelta(days=9, minutes=i),
                )
            )
        db.add_all(rows)
        await db.commit()
    d = (await client.get("/api/dashboard", params={"days": 30})).json()
    k = d["kpis"]
    assert k["total"] == 50 and k["open"] == 30 and k["high_priority"] == 30
    assert k["negative_share"] == 0.6
    assert sum(day["total"] for day in d["trend"]) == 50
    assert d["categories"][0] == {"name": "Refund Related", "count": 50, "negative_share": 0.6, "high_priority": 30}
    assert d["emerging"][0]["category"] == "Refund Related" and d["emerging"][0]["change_pct"] == 50.0
    assert any("Refund Related complaints rose 50%" in s for s in d["insights"])
    assert len(d["high_priority_open"]) == 8
    assert {s["name"]: s["count"] for s in d["sentiment"]}["Negative"] == 30


async def test_dashboard_is_cached_and_invalidated_by_writes(client):
    await client.post("/api/complaints", json={"text": "refund not received yet"})
    assert (await client.get("/api/dashboard", params={"days": 7})).json()["kpis"]["total"] == 1
    # A write invalidates the Redis cache, so the next read sees the new complaint.
    await client.post("/api/complaints", json={"text": "order delayed not delivered"})
    assert (await client.get("/api/dashboard", params={"days": 7})).json()["kpis"]["total"] == 2


async def test_dashboard_hides_change_when_previous_period_has_no_data(client):
    await client.post("/api/complaints", json={"text": "refund not received yet"})
    k = (await client.get("/api/dashboard", params={"days": 7})).json()["kpis"]
    assert k["total"] == 1 and k["total_change_pct"] is None


def test_import_day_shift_lands_newest_record_yesterday():
    from scripts.import_dataset import day_shift

    latest = datetime(2023, 8, 31, 23, 58, tzinfo=UTC)
    now = datetime(2026, 10, 4, 0, 30, tzinfo=UTC)
    shifted = latest + day_shift(latest, now)
    assert shifted.date() == datetime(2026, 10, 3).date() and shifted < now
