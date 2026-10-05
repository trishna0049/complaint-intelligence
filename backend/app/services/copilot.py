"""AI copilot on a ticket: generate (or regenerate) a summary, likely root cause, next steps and a draft reply, then
let a person accept (optionally edited), or discard the draft.

Responsible-AI rules from the spec, enforced here:
* The AI never sends a reply on its own. A draft only reaches the customer when an agent accepts it, which posts
  the agent's final text as a comment marked `ai_assisted` — the agent is its author.
* Personal data is masked before any text goes to the LLM (complaint and conversation, see app.ai.llm).
* Every output stores its provider, model, prompt version and the triage confidence / model version it built on.

Review states of a copilot run: pending -> accepted | discarded, or superseded when a newer run replaces it.
"""

from __future__ import annotations

import asyncio
import difflib
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import PROMPT_VERSION, generate_insight
from app.models import AIAnalysis, Ticket, User
from app.repositories import tickets as repo
from app.services import tickets as tickets_svc

PENDING, ACCEPTED, DISCARDED, SUPERSEDED = "pending", "accepted", "discarded", "superseded"
CONVERSATION_TURNS = 6  # most recent comments given to the model as context
CONVERSATION_CHARS = 1_000  # per comment


def _now() -> datetime:
    return datetime.now(UTC)


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail={"code": "draft_not_pending", "message": message})


def _normalise(text: str | None) -> str:
    return " ".join((text or "").split())


async def generate(db: AsyncSession, user: User, ticket_id: int) -> AIAnalysis:
    """Run the copilot. A previous pending draft on the ticket becomes `superseded` (regenerate)."""
    t = await tickets_svc.get_ticket(db, user, ticket_id)
    comments = await repo.comments(db, t.id)
    conversation = [
        {
            "author": "Support (reply to customer)" if c.ai_assisted else "Support team",
            "body": c.body[:CONVERSATION_CHARS],
        }
        for c in comments[-CONVERSATION_TURNS:]
    ]
    context = {
        "category": t.category,
        "intent": t.intent,
        "sentiment": t.sentiment,
        "priority": t.priority,
        "channel": t.channel,
        "product": t.product,
        "amount_inr": t.amount_inr,
        "entities": t.entities,
        "conversation": conversation,
    }
    names = sorted({n for n in [t.customer_name, *(c.author.name for c in comments if c.author)] if n})
    # End the read transaction before the (possibly slow) LLM call so no connection sits idle in a transaction.
    await db.commit()
    run = await asyncio.to_thread(generate_insight, t.description, context, names or None)

    superseded = await db.execute(
        update(AIAnalysis)
        .where(AIAnalysis.ticket_id == t.id, AIAnalysis.kind == "copilot", AIAnalysis.draft_status == PENDING)
        .values(draft_status=SUPERSEDED)
    )
    analysis = tickets_svc.triage_analysis(t)
    analysis.kind = "copilot"
    analysis.summary = run.insight.summary
    analysis.root_cause = run.insight.root_cause
    analysis.key_issues = run.insight.key_issues
    analysis.recommendations = run.insight.recommended_actions
    analysis.draft_response = run.insight.customer_reply
    analysis.draft_status = PENDING
    analysis.provider = run.provider
    analysis.model = (run.usage or {}).get("model") or run.model
    analysis.prompt_version = PROMPT_VERSION
    analysis.usage = run.usage
    await repo.add_analysis(db, analysis)
    t = await tickets_svc.get_ticket(db, user, ticket_id)
    tickets_svc.record_event(
        db,
        t,
        "copilot_generated",
        user,
        analysis_id=analysis.id,
        provider=analysis.provider,
        model=analysis.model,
        prompt_version=PROMPT_VERSION,
        regenerated=(superseded.rowcount or 0) > 0,
        context_comments=len(conversation),
    )
    await db.commit()
    await db.refresh(analysis, ["reviewed_by"])
    return analysis


async def _pending_draft(db: AsyncSession, user: User, analysis_id: int) -> tuple[AIAnalysis, Ticket]:
    analysis = await db.scalar(
        select(AIAnalysis)
        .where(AIAnalysis.id == analysis_id, AIAnalysis.kind == "copilot")
        .with_for_update(of=AIAnalysis)
    )
    if analysis is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Draft not found")
    t = await tickets_svc.get_ticket(db, user, analysis.ticket_id)  # 404 if the ticket isn't visible to the user
    if analysis.draft_status != PENDING:
        what = {
            ACCEPTED: "was already accepted",
            DISCARDED: "was discarded",
            SUPERSEDED: "was replaced by a newer draft",
        }.get(analysis.draft_status or "", "can't be reviewed")
        raise _conflict(f"This draft {what}.")
    return analysis, t


async def accept(db: AsyncSession, user: User, analysis_id: int, response: str) -> Ticket:
    """The agent approves the reply (as written, or edited): it is posted as their comment, marked AI-assisted."""
    analysis, t = await _pending_draft(db, user, analysis_id)
    edited = _normalise(response) != _normalise(analysis.draft_response)
    similarity = round(difflib.SequenceMatcher(None, analysis.draft_response or "", response).ratio(), 3)
    comment = await tickets_svc.insert_comment(db, user, t, response, ai_assisted=True, analysis_id=analysis.id)
    analysis.draft_status = ACCEPTED
    analysis.reviewed_by_id, analysis.reviewed_at = user.id, _now()
    analysis.final_response, analysis.edited, analysis.comment_id = response, edited, comment.id
    tickets_svc.record_event(
        db,
        t,
        "copilot_accepted",
        user,
        analysis_id=analysis.id,
        comment_id=comment.id,
        edited=edited,
        similarity=similarity,
    )
    await tickets_svc.commit(db)
    return await tickets_svc.get_ticket(db, user, t.id)


async def discard(db: AsyncSession, user: User, analysis_id: int, reason: str | None) -> Ticket:
    analysis, t = await _pending_draft(db, user, analysis_id)
    analysis.draft_status = DISCARDED
    analysis.reviewed_by_id, analysis.reviewed_at = user.id, _now()
    analysis.discard_reason = reason
    t.updated_at = _now()
    tickets_svc.record_event(db, t, "copilot_discarded", user, analysis_id=analysis.id, reason=reason)
    await tickets_svc.commit(db)
    return await tickets_svc.get_ticket(db, user, t.id)
