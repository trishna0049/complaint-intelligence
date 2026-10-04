"""Database queries for tickets and their AI analyses. No business rules here — only reads and writes."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AIAnalysis, Ticket

PRIORITY_ORDER = ["Low", "Medium", "High", "Critical"]


def priority_rank(column: Any = Ticket.priority) -> Any:
    """Numeric rank for ORDER BY (Critical = 4 ... Low = 1)."""
    return case({p: i + 1 for i, p in enumerate(PRIORITY_ORDER)}, value=column, else_=0)


async def add(db: AsyncSession, ticket: Ticket) -> Ticket:
    db.add(ticket)
    await db.flush()
    await db.refresh(ticket)
    return ticket


async def get(db: AsyncSession, ticket_id: int) -> Ticket | None:
    return await db.get(Ticket, ticket_id)


def _filtered(
    *,
    q: str | None = None,
    status: str | None = None,
    category: str | None = None,
    sentiment: str | None = None,
    priority: str | None = None,
    channel: str | None = None,
    source: str | None = None,
    needs_review: bool | None = None,
) -> Select[tuple[Ticket]]:
    stmt = select(Ticket)
    if q:
        term = q.strip()
        stmt = stmt.where(
            or_(
                Ticket.description.ilike(f"%{term}%"),
                Ticket.subject.ilike(f"%{term}%"),
                Ticket.ticket_number == term.upper(),
                Ticket.order_id == term,
            )
        )
    for column, value in (
        (Ticket.status, status),
        (Ticket.category, category),
        (Ticket.sentiment, sentiment),
        (Ticket.priority, priority),
        (Ticket.channel, channel),
        (Ticket.source, source),
    ):
        if value:
            stmt = stmt.where(column == value)
    if needs_review is not None:
        stmt = stmt.where(Ticket.needs_review.is_(needs_review))
    return stmt


async def search(
    db: AsyncSession, *, sort: str = "newest", page: int = 1, page_size: int = 25, **filters: Any
) -> tuple[list[Ticket], int]:
    stmt = _filtered(**filters)
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    if sort == "priority":
        stmt = stmt.order_by(priority_rank().desc(), Ticket.created_at.desc())
    elif sort == "oldest":
        stmt = stmt.order_by(Ticket.created_at.asc(), Ticket.id.asc())
    else:
        stmt = stmt.order_by(Ticket.created_at.desc(), Ticket.id.desc())
    rows = (await db.scalars(stmt.limit(page_size).offset((page - 1) * page_size))).all()
    return list(rows), total


async def add_analysis(db: AsyncSession, analysis: AIAnalysis) -> AIAnalysis:
    db.add(analysis)
    await db.flush()
    await db.refresh(analysis)
    return analysis
