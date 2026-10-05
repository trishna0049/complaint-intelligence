"""Copilot completion: root cause, prompt version, regenerate (supersede), accept (as is / edited) and discard, the
conversation as masked context, and the rule that the AI never posts anything by itself."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import func, select

from app.ai import llm
from app.core.db import SessionLocal
from app.models import AIAnalysis, TicketComment

SPEC = {
    "description": "I was charged twice for my order of ₹12,500 and have already contacted support three times.",
    "customer_name": "Ravi Kumar",
    "channel": "Email",
}


async def ticket(client) -> dict:
    res = await client.post("/api/v1/tickets", json=SPEC)
    assert res.status_code == 201
    return res.json()


async def run(client, tid: int) -> dict:
    res = await client.post("/api/v1/ai/draft-response", json={"ticket_id": tid})
    assert res.status_code == 201, res.text
    return res.json()


def events(detail: dict, kind: str) -> list[dict]:
    return [e["metadata"] for e in detail["timeline"] if e["event_type"] == kind]


async def comment_count() -> int:
    async with SessionLocal() as db:
        return await db.scalar(select(func.count()).select_from(TicketComment)) or 0


async def test_generate_stores_root_cause_versions_and_a_pending_draft(client, org):
    t = await ticket(client)
    a = await run(client, t["id"])
    assert a["root_cause"].startswith("Likely a duplicate capture")
    assert a["prompt_version"] == llm.PROMPT_VERSION == "copilot-v2" and a["model"] == "mock-copilot-v2"
    assert a["model_version"] == t["model_version"] and a["confidence"] == t["category_confidence"]
    assert a["draft_status"] == "pending" and a["reviewed_by"] is None and a["final_response"] is None
    detail = (await client.get(f"/api/v1/tickets/{t['id']}")).json()
    assert detail["copilot"]["id"] == a["id"]
    (meta,) = events(detail, "copilot_generated")
    assert meta["regenerated"] is False and meta["prompt_version"] == "copilot-v2"
    # Responsible AI: generating a draft never posts anything.
    assert await comment_count() == 0 and detail["first_response_at"] is None


async def test_regenerate_supersedes_the_previous_draft(client, org):
    t = await ticket(client)
    first = await run(client, t["id"])
    second = await run(client, t["id"])
    async with SessionLocal() as db:
        rows = dict(
            (await db.execute(select(AIAnalysis.id, AIAnalysis.draft_status).where(AIAnalysis.kind == "copilot"))).all()
        )
    assert rows == {first["id"]: "superseded", second["id"]: "pending"}
    detail = (await client.get(f"/api/v1/tickets/{t['id']}")).json()
    assert detail["copilot"]["id"] == second["id"]
    assert [m["regenerated"] for m in events(detail, "copilot_generated")] == [False, True]
    res = await client.post(f"/api/v1/ai/drafts/{first['id']}/accept", json={"response": "old"})
    assert res.status_code == 409 and "replaced by a newer draft" in res.json()["detail"]["message"]


async def test_accept_as_is_posts_the_agents_ai_assisted_comment(client, agent_client, org):
    t = await ticket(client)  # routed to Arjun
    a = await run(agent_client, t["id"])
    res = await agent_client.post(f"/api/v1/ai/drafts/{a['id']}/accept", json={"response": a["draft_response"]})
    assert res.status_code == 200, res.text
    detail = res.json()
    (c,) = detail["comments"]
    assert (
        c["ai_assisted"] is True and c["author"]["name"] == "Arjun Agent" and c["body"] == a["draft_response"].strip()
    )
    assert detail["first_response_at"] is not None
    cp = detail["copilot"]
    assert cp["draft_status"] == "accepted" and cp["edited"] is False and cp["comment_id"] == c["id"]
    assert cp["reviewed_by"]["name"] == "Arjun Agent" and cp["reviewed_at"] and cp["final_response"] == c["body"]
    (meta,) = events(detail, "copilot_accepted")
    assert meta["edited"] is False and meta["similarity"] == 1.0
    assert events(detail, "comment_added")[-1]["analysis_id"] == a["id"]
    again = await agent_client.post(f"/api/v1/ai/drafts/{a['id']}/accept", json={"response": "twice"})
    assert again.status_code == 409 and "already accepted" in again.json()["detail"]["message"]
    assert await comment_count() == 1


async def test_accept_edited_records_the_final_text_and_the_edit(client, org):
    t = await ticket(client)
    a = await run(client, t["id"])
    final = "Hello Ravi, I have confirmed the duplicate debit and raised a reversal of ₹12,500 (ref RV-1182)."
    detail = (await client.post(f"/api/v1/ai/drafts/{a['id']}/accept", json={"response": f"  {final}  "})).json()
    cp = detail["copilot"]
    assert cp["edited"] is True and cp["final_response"] == final and cp["draft_response"] == a["draft_response"]
    assert detail["comments"][0]["body"] == final
    assert 0 <= events(detail, "copilot_accepted")[0]["similarity"] < 1
    # Whitespace-only changes don't count as an edit.
    b = await run(client, t["id"])
    spaced = "\n\n".join(b["draft_response"].split("\n\n")) + "  "
    detail = (await client.post(f"/api/v1/ai/drafts/{b['id']}/accept", json={"response": spaced})).json()
    assert detail["copilot"]["edited"] is False


async def test_discard_then_regenerate(client, org):
    t = await ticket(client)
    a = await run(client, t["id"])
    detail = (await client.post(f"/api/v1/ai/drafts/{a['id']}/discard", json={"reason": "Wrong tone"})).json()
    cp = detail["copilot"]
    assert cp["draft_status"] == "discarded" and cp["discard_reason"] == "Wrong tone" and cp["reviewed_by"]
    assert events(detail, "copilot_discarded") == [{"analysis_id": a["id"], "reason": "Wrong tone"}]
    assert detail["comments"] == []
    res = await client.post(f"/api/v1/ai/drafts/{a['id']}/accept", json={"response": "x"})
    assert res.status_code == 409 and "was discarded" in res.json()["detail"]["message"]
    b = await run(client, t["id"])
    assert b["draft_status"] == "pending"
    assert (await client.post(f"/api/v1/ai/drafts/{b['id']}/discard", json={})).status_code == 200


async def test_review_permissions_and_validation(client, other_agent_client, org):
    t = await ticket(client)  # Payments Support: Olga (Returns) can't see it
    a = await run(client, t["id"])
    assert (
        await other_agent_client.post(f"/api/v1/ai/drafts/{a['id']}/accept", json={"response": "hi"})
    ).status_code == 404
    assert (await other_agent_client.post(f"/api/v1/ai/drafts/{a['id']}/discard", json={})).status_code == 404
    assert (await other_agent_client.post("/api/v1/ai/draft-response", json={"ticket_id": t["id"]})).status_code == 404
    assert (await client.post(f"/api/v1/ai/drafts/{a['id']}/accept", json={"response": "   "})).status_code == 422
    assert (await client.post("/api/v1/ai/drafts/99999/accept", json={"response": "hi"})).status_code == 404
    async with SessionLocal() as db:
        triage_id = await db.scalar(select(AIAnalysis.id).where(AIAnalysis.kind == "triage"))
    assert (await client.post(f"/api/v1/ai/drafts/{triage_id}/discard", json={})).status_code == 404  # not a draft


async def test_conversation_is_context_and_is_masked(client, org, monkeypatch):
    seen: dict[str, Any] = {}
    real = llm.MockProvider.generate

    def spy(self, text: str, context: dict[str, Any]):  # type: ignore[no-untyped-def]
        seen.update(text=text, context=context)
        return real(self, text, context)

    monkeypatch.setattr(llm.MockProvider, "generate", spy)
    t = await ticket(client)
    await client.post(f"/api/v1/tickets/{t['id']}/comments", json={"body": "Ravi Kumar called from 9876543210 again."})
    a = await run(client, t["id"])
    (turn,) = seen["context"]["conversation"]
    assert turn["author"] == "Support team"
    assert "9876543210" not in turn["body"] and "Ravi Kumar" not in turn["body"] and "[PHONE]" in turn["body"]
    assert "Ravi Kumar" not in seen["text"]
    assert a["recommendations"][0].startswith("Follow up on the latest note")
    detail = (await client.get(f"/api/v1/tickets/{t['id']}")).json()
    assert events(detail, "copilot_generated")[0]["context_comments"] == 1


def test_prompt_includes_the_conversation():
    prompt = llm.build_user_prompt(
        "charged twice",
        {
            "category": "Payments related",
            "conversation": [{"author": "Support team", "body": "Raised with the gateway"}],
        },
    )
    assert "Conversation so far" in prompt and "- Support team: Raised with the gateway" in prompt


@pytest.mark.parametrize("category", [*llm.PLAYBOOK, "Something else"])
def test_mock_gives_every_category_a_root_cause(category):
    out, _ = llm.MockProvider().generate("text", {"category": category})
    assert out.root_cause and (out.root_cause.startswith("Likely") or out.root_cause.startswith("Unclear"))
