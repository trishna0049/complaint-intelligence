from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.ai.llm import PROMPT_VERSION, generate_insight
from app.ai.priority import BASE_PRIORITY, decide_priority
from app.ai.triage import TriageResult, triage
from app.models import AIInsight, Complaint
from app.schemas import ComplaintCreate, ComplaintUpdate
from app.services.dashboard import invalidate_cache


def next_reference(db: Session) -> str:
    last = db.scalar(select(func.max(Complaint.id))) or 0
    return f"CMP-{last + 1:06d}"


def default_subject(text: str) -> str:
    first = text.strip().split("\n")[0]
    return first if len(first) <= 80 else first[:77].rstrip() + "…"


def create_complaint(db: Session, data: ComplaintCreate) -> Complaint:
    result = triage(
        data.text, channel=data.channel, product=data.product, amount_inr=data.amount_inr, order_id=data.order_id
    )
    complaint = Complaint(
        reference=next_reference(db),
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
    db.add(complaint)
    db.commit()
    invalidate_cache()
    db.refresh(complaint)
    return complaint


def apply_triage(c: Complaint, r: TriageResult) -> None:
    c.category, c.category_confidence = r.category, r.category_confidence
    c.intent, c.intent_confidence = r.intent, r.intent_confidence
    c.sentiment, c.sentiment_score = r.sentiment, r.sentiment_score
    c.priority, c.priority_reasons = r.priority, r.priority_reasons
    c.entities, c.needs_review = r.entities, r.needs_review
    c.model_version, c.labels_from = r.model_version, "model"


def list_complaints(
    db: Session,
    *,
    q: str | None = None,
    status: str | None = None,
    category: str | None = None,
    sentiment: str | None = None,
    priority: str | None = None,
    channel: str | None = None,
    source: str | None = None,
    needs_review: bool | None = None,
    sort: str = "newest",
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[Complaint], int]:
    stmt = select(Complaint)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Complaint.text.ilike(like),
                Complaint.subject.ilike(like),
                Complaint.reference == q.strip().upper(),
                Complaint.order_id == q.strip(),
            )
        )
    for column, value in (
        (Complaint.status, status),
        (Complaint.category, category),
        (Complaint.sentiment, sentiment),
        (Complaint.priority, priority),
        (Complaint.channel, channel),
        (Complaint.source, source),
    ):
        if value:
            stmt = stmt.where(column == value)
    if needs_review is not None:
        stmt = stmt.where(Complaint.needs_review.is_(needs_review))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort == "priority":
        rank = func.instr("LowMediumHighCritical", Complaint.priority)  # Critical has the highest position
        stmt = stmt.order_by(rank.desc(), Complaint.created_at.desc())
    elif sort == "oldest":
        stmt = stmt.order_by(Complaint.created_at.asc())
    else:
        stmt = stmt.order_by(Complaint.created_at.desc(), Complaint.id.desc())
    rows = db.scalars(stmt.limit(page_size).offset((page - 1) * page_size)).all()
    return list(rows), total


def get_complaint(db: Session, complaint_id: int) -> Complaint:
    c = db.get(Complaint, complaint_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return c


def update_complaint(db: Session, complaint_id: int, data: ComplaintUpdate) -> Complaint:
    c = get_complaint(db, complaint_id)
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
    db.commit()
    invalidate_cache()
    db.refresh(c)
    return c


def create_insight(db: Session, complaint_id: int) -> AIInsight:
    c = get_complaint(db, complaint_id)
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
    run = generate_insight(c.text, context, known_names=[c.customer_name] if c.customer_name else None)
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
    db.add(insight)
    db.commit()
    db.refresh(insight)
    return insight
