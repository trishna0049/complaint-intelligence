"""Retrieval: the fusion rules, the hashing embedder, which tickets get embedded, similar tickets (hybrid,
visibility-scoped), knowledge-base search and CRUD permissions, the backfill script, and RAG grounding of the
copilot. Tests use the deterministic hashing embedder (ENABLE_TRANSFORMERS=false); MiniLM itself is checked on
fixed examples in test_retrieval_minilm.py."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from sqlalchemy import func, select

from app.ai import embeddings as emb
from app.ai import llm
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import AuditLog, KnowledgeArticle, Ticket, TicketEmbedding
from app.repositories.retrieval import or_query
from app.services.retrieval import fuse
from scripts import embed_tickets
from scripts.knowledge_seed import ARTICLES
from scripts.seed_knowledge import seed_knowledge

CHARGED = {"description": "I was charged twice for my order and the money was debited two times from my card"}


@pytest.fixture(autouse=True)
def _loose_threshold(monkeypatch):
    # Hashing vectors score lower than MiniLM's; the rule (drop weak vector matches) is tested separately below.
    monkeypatch.setattr(get_settings(), "similar_min_score", 0.05)
    monkeypatch.setattr(get_settings(), "article_min_score", 0.05)


@pytest.fixture
async def kb():
    async with SessionLocal() as db:
        return await seed_knowledge(db)


# ------------------------------------------------------------------------------------------------ unit
def test_fusion_rewards_agreement_and_drops_weak_vector_matches():
    vector = [(1, 0.9), (2, 0.8), (3, 0.2)]
    keyword = [(2, 5.0), (4, 3.0), (5, 1.0)]
    hits = fuse(vector, keyword, k=60, min_similarity=0.3, keyword_only_top=2)
    assert [h.id for h in hits] == [2, 1, 4]  # 2: both lists; 3: too weak; 5: keyword-only beyond the top 2
    assert [h.matched_by for h in hits] == ["both", "meaning", "keywords"]
    assert hits[0].similarity == 0.8 and hits[2].similarity is None


def test_fusion_boost_nudges_but_does_not_override():
    vector = [(1, 0.9), (2, 0.85), (3, 0.5)]
    boosted = fuse(vector, [], k=60, min_similarity=0.3, keyword_only_top=0, boost={2})
    assert [h.id for h in boosted] == [2, 1, 3]
    assert [h.id for h in fuse(vector, [], k=60, min_similarity=0.3, keyword_only_top=0, boost={3})] == [1, 3, 2]


def test_or_query_only_ever_contains_plain_words():
    assert or_query("Refund NOT received!! refund") == "refund | not | received"
    assert or_query("a & b | !c:* <-> ')--") is None  # nothing of 3+ characters survives
    assert or_query("x" * 5 + " " + " ".join(f"w{i:03d}" for i in range(50))).count("|") == 31  # capped at 32 terms


def test_hashing_embedder_is_deterministic_normalised_and_meaningful():
    e = emb.HashingEmbedder()
    a, b, c = e.encode(["refund not received", "my refund was not received yet", "app crashes on login"])
    assert np.allclose(a, e.encode(["refund not received"])[0]) and abs(np.linalg.norm(a) - 1) < 1e-5
    assert a @ b > a @ c


def test_only_real_complaint_text_is_embedded():
    assert emb.worth_embedding("customer", "help me") is True
    assert emb.worth_embedding("dataset_remark", "Good") is False
    assert emb.worth_embedding("dataset_remark", "refund still not received") is True
    assert emb.worth_embedding("template", "Installation/demo request for an order related issue") is False
    assert emb.ticket_text("Charged twice", "Charged twice for my order") == "Charged twice for my order"
    assert emb.ticket_text("Refund", "Still waiting") == "Refund. Still waiting"


# ------------------------------------------------------------------------------------------------ similar tickets
async def create(client, payload) -> dict:
    res = await client.post("/api/v1/tickets", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


async def test_new_tickets_are_embedded_and_find_each_other(client, org):
    first = await create(client, CHARGED)
    dup = await create(client, {"description": "Money debited two times for one order, charged twice on my card"})
    other = await create(client, {"description": "The app crashes every time I open the login screen"})
    async with SessionLocal() as db:
        rows = (await db.execute(select(TicketEmbedding.ticket_id, TicketEmbedding.model_name))).all()
    assert {r[0] for r in rows} == {first["id"], dup["id"], other["id"]}
    assert {r[1] for r in rows} == {"hashing-384-v1"}

    res = await client.get(f"/api/v1/tickets/{first['id']}/similar")
    assert res.status_code == 200
    items = res.json()
    assert items[0]["id"] == dup["id"] and items[0]["matched_by"] == "both" and items[0]["similarity"] > 0.2
    assert first["id"] not in {i["id"] for i in items}  # never itself
    assert items[0]["ticket_number"] and items[0]["snippet"].startswith("Money debited")


async def test_similar_tickets_respect_visibility(client, agent_client, other_agent_client, org):
    payments = await create(client, CHARGED)  # Payments Support (Arjun)
    twin = await create(client, {"description": "charged twice, money debited two times from my card"})
    returns = await create(other_agent_client, {"description": "charged twice and want to return the item, pickup"})
    seen_by_arjun = {i["id"] for i in (await agent_client.get(f"/api/v1/tickets/{payments['id']}/similar")).json()}
    assert twin["id"] in seen_by_arjun and returns["id"] not in seen_by_arjun  # Olga's team's ticket stays hidden
    seen_by_admin = {i["id"] for i in (await client.get(f"/api/v1/tickets/{payments['id']}/similar")).json()}
    assert {twin["id"], returns["id"]} <= seen_by_admin
    assert (await other_agent_client.get(f"/api/v1/tickets/{payments['id']}/similar")).status_code == 404


async def test_backfill_embeds_dataset_history_once(client, org):
    async with SessionLocal() as db:
        db.add_all(
            [
                Ticket(
                    subject="Refund — Refund Related",
                    description="My refund is still not received in my bank",
                    source="dataset",
                    description_source="dataset_remark",
                    status="CLOSED",
                ),
                Ticket(
                    subject="Feedback",
                    description="Good",
                    source="dataset",
                    description_source="dataset_remark",
                    status="CLOSED",
                ),
                Ticket(
                    subject="Template",
                    description="Refund enquiry about an order (no remark)",
                    source="dataset",
                    description_source="template",
                    status="CLOSED",
                ),
            ]
        )
        await db.commit()
    assert await embed_tickets.run(batch=2) == 1  # only the informative remark
    assert await embed_tickets.run(batch=2) == 0  # idempotent
    async with SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(TicketEmbedding)) == 1
    t = await create(client, {"description": "refund not received in my bank account yet"})
    hits = (await client.get(f"/api/v1/tickets/{t['id']}/similar")).json()
    assert hits[0]["snippet"] == "My refund is still not received in my bank"


# ------------------------------------------------------------------------------------------------ knowledge base
async def test_seeded_knowledge_base_is_searchable(client, agent_client, kb):
    assert kb == {"created": len(ARTICLES), "embedded": len(ARTICLES)}
    async with SessionLocal() as db:
        assert await seed_knowledge(db) == {"created": 0, "embedded": 0}  # idempotent
    for query, expected in [
        ("refund not credited to my bank, what is the refund timeline", "Refund policy and timelines"),
        ("charged twice duplicate payment", "Duplicate or double payment for one order"),
        ("OTP not received", "OTP not received"),
        ("reverse pickup not done for my return", "Return and reverse pickup policy"),
    ]:
        hits = (await agent_client.get("/api/v1/knowledge/search", params={"q": query, "limit": 3})).json()
        assert expected in [h["title"] for h in hits], (query, [h["title"] for h in hits])
    payments = (await client.get("/api/v1/knowledge", params={"category": "Payments related"})).json()
    assert payments["total"] == 2 and all(i["category"] == "Payments related" for i in payments["items"])
    filtered = (await client.get("/api/v1/knowledge/search", params={"q": "refund", "category": "Returns"})).json()
    assert filtered and all(h["category"] == "Returns" for h in filtered)
    assert (await client.get("/api/v1/knowledge/search", params={"q": ""})).json() == []


async def test_articles_for_a_ticket(client, agent_client, other_agent_client, kb):
    t = await create(client, {"description": "Duplicate payment: I was charged twice for one order"})
    hits = (await agent_client.get("/api/v1/knowledge/search", params={"ticket_id": t["id"]})).json()
    # The category boost puts a Payments article first; MiniLM's exact order is checked in test_retrieval_minilm.py.
    assert hits[0]["category"] == "Payments related"
    assert "Duplicate or double payment for one order" in [h["title"] for h in hits[:3]]
    assert (await other_agent_client.get("/api/v1/knowledge/search", params={"ticket_id": t["id"]})).status_code == 404


async def test_knowledge_crud_is_admin_only_audited_and_reembeds(client, agent_client, org):
    body = {
        "title": "Gift card balance",
        "body": "Gift card balances never expire and can be combined with UPI.",
        "category": "Offers & Cashback",
    }
    assert (await agent_client.post("/api/v1/knowledge", json=body)).status_code == 403
    res = await client.post("/api/v1/knowledge", json=body)
    assert res.status_code == 201
    art = res.json()
    assert art["updated_by"]["name"] == "Ada Admin" and art["usage_count"] == 0
    assert (await agent_client.get(f"/api/v1/knowledge/{art['id']}")).json()["title"] == "Gift card balance"
    assert (await client.post("/api/v1/knowledge", json=body)).status_code == 409
    assert (await client.post("/api/v1/knowledge", json={**body, "title": "X1", "category": "Nope"})).status_code == 422

    async def vector() -> list[float]:
        async with SessionLocal() as db:
            return list((await db.get(KnowledgeArticle, art["id"])).embedding)

    before = await vector()
    assert (await agent_client.patch(f"/api/v1/knowledge/{art['id']}", json={"category": None})).status_code == 403
    general = (await client.patch(f"/api/v1/knowledge/{art['id']}", json={"category": None})).json()
    assert general["category"] is None and await vector() == before  # same text, same vector
    new_body = "Gift cards can be used for any order and are refunded to the gift card on cancellation."
    await client.patch(f"/api/v1/knowledge/{art['id']}", json={"body": new_body})
    assert await vector() != before
    hits = (await client.get("/api/v1/knowledge/search", params={"q": "gift card refunded on cancellation"})).json()
    assert hits[0]["id"] == art["id"]
    assert (await agent_client.delete(f"/api/v1/knowledge/{art['id']}")).status_code == 403
    assert (await client.delete(f"/api/v1/knowledge/{art['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/knowledge/{art['id']}")).status_code == 404
    async with SessionLocal() as db:
        actions = (await db.scalars(select(AuditLog.action).where(AuditLog.action.like("knowledge.%")))).all()
    assert actions == ["knowledge.create", "knowledge.update", "knowledge.update", "knowledge.delete"]


# ------------------------------------------------------------------------------------------------ RAG
async def test_copilot_is_grounded_in_articles_and_similar_tickets(client, org, kb, monkeypatch):
    seen: dict[str, Any] = {}
    real = llm.MockProvider.generate

    def spy(self, text: str, context: dict[str, Any]):  # type: ignore[no-untyped-def]
        seen["context"] = context
        return real(self, text, context)

    monkeypatch.setattr(llm.MockProvider, "generate", spy)
    await create(client, {**CHARGED, "customer_name": "Meera Iyer", "description": CHARGED["description"] + ". Meera"})
    t = await create(
        client, {"description": "Charged twice for one order, money debited two times", "channel": "Email"}
    )
    a = (await client.post("/api/v1/ai/draft-response", json={"ticket_id": t["id"]})).json()

    refs = seen["context"]["references"]
    assert [r["ref"] for r in refs][:2] == ["A1", "A2"] and any(r["ref"] == "T1" for r in refs)
    first_article = refs[0]["title"]
    assert first_article in {"Duplicate or double payment for one order", "Money debited but order not placed"}
    assert all("Meera" not in r["text"] for r in refs)  # other customers' names masked
    assert "References:" in llm.build_user_prompt("x", seen["context"])

    grounding = {g["ref"]: g for g in a["grounding"]}
    assert grounding["A1"]["cited"] is True and grounding["T1"]["cited"] is True and grounding["A2"]["cited"] is False
    assert grounding["T1"]["ticket_number"].startswith("INC-")
    assert f"Follow the help article “{first_article}”" in a["recommendations"]
    async with SessionLocal() as db:
        uses = dict((await db.execute(select(KnowledgeArticle.title, KnowledgeArticle.usage_count))).all())
    assert uses[first_article] == 1 and sum(uses.values()) == 1  # only the cited article counts a use
    detail = (await client.get(f"/api/v1/tickets/{t['id']}")).json()
    meta = next(e["metadata"] for e in detail["timeline"] if e["event_type"] == "copilot_generated")
    assert meta["references"] == len(refs) and meta["cited"] == ["A1", "T1"]


async def test_unknown_citations_from_the_model_are_ignored(client, org, kb, monkeypatch):
    real = llm.MockProvider.generate

    def hallucinating(self, text: str, context: dict[str, Any]):  # type: ignore[no-untyped-def]
        out, usage = real(self, text, context)
        return out.model_copy(update={"references_used": ["A1", "A9", "T7"]}), usage

    monkeypatch.setattr(llm.MockProvider, "generate", hallucinating)
    t = await create(client, CHARGED)
    a = (await client.post("/api/v1/ai/draft-response", json={"ticket_id": t["id"]})).json()
    assert [g["ref"] for g in a["grounding"] if g["cited"]] == ["A1"]


async def test_whole_complaints_dont_pull_in_keyword_only_articles(client, kb, monkeypatch):
    """Typed queries keep keyword-only hits (exact terms); a ticket's whole text only re-ranks meaning matches."""
    from app.repositories import retrieval as repo
    from app.services import retrieval

    async def no_vectors(*args, **kwargs):
        return []

    monkeypatch.setattr(repo, "nearest_articles", no_vectors)
    t = await create(client, {"description": "OTP not received when I try to log in"})
    async with SessionLocal() as db:
        ticket = await db.get(Ticket, t["id"])
        assert [h.article.title for h in await retrieval.search_articles(db, "OTP not received", limit=1)] == [
            "OTP not received"
        ]
        assert await retrieval.articles_for_ticket(db, ticket) == []
