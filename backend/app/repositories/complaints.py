"""Database queries for complaints. No business rules here — only reads and writes."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AIInsight, Complaint

PRIORITY_ORDER = ["Low", "Medium", "High", "Critical"]


def priority_rank(column: Any = Complaint.priority) -> Any:
    """Numeric rank for ORDER BY (Critical = 4 ... Low = 1)."""
    return case({p: i + 1 for i, p in enumerate(PRIORITY_ORDER)}, value=column, else_=0)


async def add(db: AsyncSession, complaint: Complaint) -> Complaint:
    db.add(complaint)
    await db.flush()
    await db.refresh(complaint)
    return complaint


async def get(db: AsyncSession, complaint_id: int) -> Complaint | None:
    return await db.get(Complaint, complaint_id)


def _filtered(
    *,
    q: str | None,
    status: str | None,
    category: str | None,
    sentiment: str | None,
    priority: str | None,
    channel: str | None,
    source: str | None,
    needs_review: bool | None,
) -> Select[tuple[Complaint]]:
    stmt = select(Complaint)
    if q:
        term = q.strip()
        stmt = stmt.where(
            or_(
                Complaint.text.ilike(f"%{term}%"),
                Complaint.subject.ilike(f"%{term}%"),
                Complaint.reference == term.upper(),
                Complaint.order_id == term,
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
    return stmt


async def search(
    db: AsyncSession, *, sort: str = "newest", page: int = 1, page_size: int = 25, **filters: Any
) -> tuple[list[Complaint], int]:
    stmt = _filtered(**filters)
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    if sort == "priority":
        stmt = stmt.order_by(priority_rank().desc(), Complaint.created_at.desc())
    elif sort == "oldest":
        stmt = stmt.order_by(Complaint.created_at.asc(), Complaint.id.asc())
    else:
        stmt = stmt.order_by(Complaint.created_at.desc(), Complaint.id.desc())
    rows = (await db.scalars(stmt.limit(page_size).offset((page - 1) * page_size))).all()
    return list(rows), total


async def add_insight(db: AsyncSession, insight: AIInsight) -> AIInsight:
    db.add(insight)
    await db.flush()
    await db.refresh(insight)
    return insight
