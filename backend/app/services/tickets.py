from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import PROMPT_VERSION, generate_insight
from app.ai.priority import BASE_PRIORITY, decide_priority
from app.ai.triage import TriageResult, triage
from app.models import AIAnalysis, Ticket
from app.repositories import tickets as repo
from app.schemas.tickets import TicketCreate, TicketUpdate
from app.services.analytics import invalidate_cache


def default_subject(text: str) -> str:
    first = text.strip().split("\n")[0]
    return first if len(first) <= 80 else first[:77].rstrip() + "…"


async def run_triage(data: TicketCreate) -> TriageResult:
    # The models are CPU-bound; keep them off the event loop.
    return await asyncio.to_thread(
        triage,
        data.description,
        channel=data.channel,
        product=data.product,
        amount_inr=data.amount_inr,
        order_id=data.order_id,
    )


async def create_ticket(db: AsyncSession, data: TicketCreate) -> Ticket:
    result = await run_triage(data)
    ticket = Ticket(
        source="new",
        subject=(data.subject or "").strip() or default_subject(data.description),
        description=data.description,
        description_source="customer",
        channel=data.channel,
        customer_name=data.customer_name,
        order_id=data.order_id or (result.entities["order_ids"][0] if result.entities["order_ids"] else None),
        product=data.product,
        amount_inr=data.amount_inr if data.amount_inr is not None else result.entities["max_amount_inr"],
        city=data.city,
        status="Open",
    )
    apply_triage(ticket, result)
    await repo.add(db, ticket)
    await repo.add_analysis(db, triage_analysis(ticket))
    await db.commit()
    await invalidate_cache()
    await db.refresh(ticket, ["analyses"])
    return ticket


def apply_triage(t: Ticket, r: TriageResult) -> None:
    t.category, t.category_confidence = r.category, r.category_confidence
    t.intent, t.intent_confidence = r.intent, r.intent_confidence
    t.sentiment, t.sentiment_score = r.sentiment, r.sentiment_score
    t.priority, t.priority_reasons = r.priority, r.priority_reasons
    t.entities, t.needs_review = r.entities, r.needs_review
    t.model_version, t.labels_from = r.model_version, "model"


def triage_analysis(t: Ticket) -> AIAnalysis:
    """Record of one triage run (every AI output stores its confidence and model version)."""
    return AIAnalysis(
        ticket_id=t.id,
        kind="triage",
        category=t.category,
        intent=t.intent,
        sentiment=t.sentiment,
        priority=t.priority,
        entities=t.entities,
        confidence=t.category_confidence,
        model_version=t.model_version,
    )


async def get_ticket(db: AsyncSession, ticket_id: int) -> Ticket:
    t = await repo.get(db, ticket_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return t


async def list_tickets(db: AsyncSession, **params: Any) -> tuple[list[Ticket], int]:
    return await repo.search(db, **params)


async def update_ticket(db: AsyncSession, ticket_id: int, data: TicketUpdate) -> Ticket:
    t = await get_ticket(db, ticket_id)
    if data.status and data.status != t.status:
        t.status = data.status
        t.resolved_at = datetime.now(UTC) if data.status == "Resolved" else None
    if data.category and data.category != t.category:
        if data.category not in BASE_PRIORITY:
            raise HTTPException(status_code=422, detail="Unknown category")
        t.category, t.category_confidence, t.needs_review, t.labels_from = data.category, 1.0, False, "human"
        decision = decide_priority(
            t.category,
            t.sentiment,
            t.amount_inr,
            bool((t.entities or {}).get("repeat_contact")),
            t.intent,
            t.description,
        )
        t.priority = decision.priority
        t.priority_reasons = [
            {"rule": "BASE", "reason": f"Base priority for {t.category}", "from": "", "to": decision.base},
            *decision.reasons,
        ]
    await db.commit()
    await invalidate_cache()
    await db.refresh(t)
    return t


def latest_copilot(t: Ticket) -> AIAnalysis | None:
    return next((a for a in t.analyses if a.kind == "copilot"), None)


async def generate_copilot(db: AsyncSession, ticket_id: int) -> AIAnalysis:
    """Ask the LLM for a summary, key issues, recommendations and a draft response (PII masked first)."""
    t = await get_ticket(db, ticket_id)
    context = {
        "category": t.category,
        "intent": t.intent,
        "sentiment": t.sentiment,
        "priority": t.priority,
        "channel": t.channel,
        "product": t.product,
        "amount_inr": t.amount_inr,
        "entities": t.entities,
    }
    # The OpenAI SDK call is blocking; run it in a worker thread.
    run = await asyncio.to_thread(
        generate_insight, t.description, context, [t.customer_name] if t.customer_name else None
    )
    analysis = triage_analysis(t)
    analysis.kind = "copilot"
    analysis.summary = run.insight.summary
    analysis.key_issues = run.insight.key_issues
    analysis.recommendations = run.insight.recommended_actions
    analysis.draft_response = run.insight.customer_reply
    analysis.provider = run.provider
    analysis.model = (run.usage or {}).get("model") or run.model
    analysis.prompt_version = PROMPT_VERSION
    analysis.usage = run.usage
    await repo.add_analysis(db, analysis)
    await db.commit()
    await db.refresh(t, ["analyses"])
    return analysis
