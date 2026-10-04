from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import PROMPT_VERSION, generate_insight
from app.ai.priority import BASE_PRIORITY, decide_priority
from app.ai.triage import TriageResult, triage
from app.models import AIInsight, Complaint
from app.repositories import complaints as repo
from app.schemas import ComplaintCreate, ComplaintUpdate
from app.services.dashboard import invalidate_cache


def default_subject(text: str) -> str:
    first = text.strip().split("\n")[0]
    return first if len(first) <= 80 else first[:77].rstrip() + "…"


async def run_triage(data: ComplaintCreate) -> TriageResult:
    # The models are CPU-bound; keep them off the event loop.
    return await asyncio.to_thread(
        triage,
        data.text,
        channel=data.channel,
        product=data.product,
        amount_inr=data.amount_inr,
        order_id=data.order_id,
    )


async def create_complaint(db: AsyncSession, data: ComplaintCreate) -> Complaint:
    result = await run_triage(data)
    complaint = Complaint(
        source="new",
        subject=(data.subject or "").strip() or default_subject(data.text),
        text=data.text,
        channel=data.channel,
        customer_name=data.customer_name,
        order_id=data.order_id or (result.entities["order_ids"][0] if result.entities["order_ids"] else None),
        product=data.product,
        amount_inr=data.amount_inr if data.amount_inr is not None else result.entities["max_amount_inr"],
        city=data.city,
        status="Open",
    )
    apply_triage(complaint, result)
    await repo.add(db, complaint)
    await db.commit()
    await invalidate_cache()
    return complaint


def apply_triage(c: Complaint, r: TriageResult) -> None:
    c.category, c.category_confidence = r.category, r.category_confidence
    c.intent, c.intent_confidence = r.intent, r.intent_confidence
    c.sentiment, c.sentiment_score = r.sentiment, r.sentiment_score
    c.priority, c.priority_reasons = r.priority, r.priority_reasons
    c.entities, c.needs_review = r.entities, r.needs_review
    c.model_version, c.labels_from = r.model_version, "model"


async def get_complaint(db: AsyncSession, complaint_id: int) -> Complaint:
    c = await repo.get(db, complaint_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return c


async def update_complaint(db: AsyncSession, complaint_id: int, data: ComplaintUpdate) -> Complaint:
    c = await get_complaint(db, complaint_id)
    if data.status and data.status != c.status:
        c.status = data.status
        c.resolved_at = datetime.now(UTC) if data.status == "Resolved" else None
    if data.category and data.category != c.category:
        if data.category not in BASE_PRIORITY:
            raise HTTPException(status_code=422, detail="Unknown category")
        c.category, c.category_confidence, c.needs_review, c.labels_from = data.category, 1.0, False, "human"
        decision = decide_priority(
            c.category, c.sentiment, c.amount_inr, bool((c.entities or {}).get("repeat_contact")), c.intent, c.text
        )
        c.priority = decision.priority
        c.priority_reasons = [
            {"rule": "BASE", "reason": f"Base priority for {c.category}", "from": "", "to": decision.base},
            *decision.reasons,
        ]
    await db.commit()
    await invalidate_cache()
    await db.refresh(c)
    return c


async def create_insight(db: AsyncSession, complaint_id: int) -> AIInsight:
    c = await get_complaint(db, complaint_id)
    context = {
        "category": c.category,
        "intent": c.intent,
        "sentiment": c.sentiment,
        "priority": c.priority,
        "channel": c.channel,
        "product": c.product,
        "amount_inr": c.amount_inr,
        "entities": c.entities,
    }
    # The OpenAI SDK call is blocking; run it in a worker thread.
    run = await asyncio.to_thread(generate_insight, c.text, context, [c.customer_name] if c.customer_name else None)
    insight = AIInsight(
        complaint_id=c.id,
        summary=run.insight.summary,
        key_issues=run.insight.key_issues,
        recommended_actions=run.insight.recommended_actions,
        customer_reply=run.insight.customer_reply,
        provider=run.provider,
        model=(run.usage or {}).get("model") or run.model,
        prompt_version=PROMPT_VERSION,
        usage=run.usage,
    )
    await repo.add_insight(db, insight)
    await db.commit()
    await db.refresh(c, ["insights"])
    return insight


async def list_complaints(db: AsyncSession, **params: Any) -> tuple[list[Complaint], int]:
    return await repo.search(db, **params)
