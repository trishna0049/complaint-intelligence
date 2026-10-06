"""Database queries for tickets, their comments, timeline events, attachments, AI analyses and customers.

No business rules here — only reads and writes. Visibility rules arrive as a ready-made SQL condition from the
ticket service (`services.tickets.visibility_clause`).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, Select, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AIAnalysis,
    Customer,
    DeadLetter,
    Ticket,
    TicketAttachment,
    TicketComment,
    TicketEvent,
    User,
)

PRIORITY_ORDER = ["Low", "Medium", "High", "Critical"]


def priority_rank(column: Any = Ticket.priority) -> Any:
    """Numeric rank for ORDER BY (Critical = 4 ... Low = 1)."""
    return case({p: i + 1 for i, p in enumerate(PRIORITY_ORDER)}, value=column, else_=0)


# ------------------------------------------------------------------------------------------------ tickets
async def add(db: AsyncSession, ticket: Ticket) -> Ticket:
    db.add(ticket)
    await db.flush()
    await db.refresh(ticket)
    return ticket


async def get(
    db: AsyncSession, ticket_id: int, *, visible: ColumnElement[bool] | None = None, for_update: bool = False
) -> Ticket | None:
    # populate_existing: always return fresh column values and relationships (after commits in the same session).
    stmt = select(Ticket).where(Ticket.id == ticket_id).execution_options(populate_existing=True)
    if visible is not None:
        stmt = stmt.where(visible)
    if for_update:
        stmt = stmt.with_for_update(of=Ticket)
    return (await db.scalars(stmt)).unique().one_or_none()


def _filtered(
    visible: ColumnElement[bool] | None,
    *,
    q: str | None = None,
    status: list[str] | None = None,
    category: str | None = None,
    sentiment: str | None = None,
    priority: str | None = None,
    channel: str | None = None,
    source: str | None = None,
    needs_review: bool | None = None,
    assignee_id: int | None = None,
    unassigned: bool = False,
    team_id: int | None = None,
    escalated: bool | None = None,
) -> Select[tuple[Ticket]]:
    stmt = select(Ticket)
    if visible is not None:
        stmt = stmt.where(visible)
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
    if status:
        stmt = stmt.where(Ticket.status.in_(status))
    for column, value in (
        (Ticket.category, category),
        (Ticket.sentiment, sentiment),
        (Ticket.priority, priority),
        (Ticket.channel, channel),
        (Ticket.source, source),
        (Ticket.team_id, team_id),
        (Ticket.assignee_id, assignee_id),
    ):
        if value:
            stmt = stmt.where(column == value)
    if unassigned:
        stmt = stmt.where(Ticket.assignee_id.is_(None))
    if needs_review is not None:
        stmt = stmt.where(Ticket.needs_review.is_(needs_review))
    if escalated is not None:
        stmt = stmt.where(Ticket.escalated_at.is_not(None) if escalated else Ticket.escalated_at.is_(None))
    return stmt


async def search(
    db: AsyncSession,
    visible: ColumnElement[bool] | None,
    *,
    sort: str = "newest",
    page: int = 1,
    page_size: int = 25,
    **filters: Any,
) -> tuple[list[Ticket], int]:
    stmt = _filtered(visible, **filters)
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    order = {
        "priority": (priority_rank().desc(), Ticket.created_at.desc()),
        "oldest": (Ticket.created_at.asc(), Ticket.id.asc()),
        "updated": (Ticket.updated_at.desc(), Ticket.id.desc()),
    }.get(sort, (Ticket.created_at.desc(), Ticket.id.desc()))
    rows = await db.scalars(stmt.order_by(*order).limit(page_size).offset((page - 1) * page_size))
    return list(rows.unique().all()), total


async def status_counts(db: AsyncSession, visible: ColumnElement[bool] | None, **filters: Any) -> dict[str, int]:
    stmt = _filtered(visible, **filters).with_only_columns(Ticket.status, func.count()).group_by(Ticket.status)
    return {s: n for s, n in (await db.execute(stmt)).all()}


async def previous_for_customer(db: AsyncSession, customer_id: int, exclude_id: int, limit: int = 10) -> list[Ticket]:
    rows = await db.scalars(
        select(Ticket)
        .where(Ticket.customer_id == customer_id, Ticket.id != exclude_id)
        .order_by(Ticket.created_at.desc())
        .limit(limit)
    )
    return list(rows.unique().all())


# ------------------------------------------------------------------------------------------------ analyses
async def add_analysis(db: AsyncSession, analysis: AIAnalysis) -> AIAnalysis:
    db.add(analysis)
    await db.flush()
    await db.refresh(analysis)
    return analysis


# ------------------------------------------------------------------------------- comments / events / files
def add_event(
    db: AsyncSession, ticket_id: int, event_type: str, actor_id: int | None, metadata: dict[str, Any] | None = None
) -> TicketEvent:
    event = TicketEvent(ticket_id=ticket_id, event_type=event_type, actor_id=actor_id, metadata_=metadata or None)
    db.add(event)
    return event


async def events(db: AsyncSession, ticket_id: int) -> list[TicketEvent]:
    rows = await db.scalars(
        select(TicketEvent).where(TicketEvent.ticket_id == ticket_id).order_by(TicketEvent.created_at, TicketEvent.id)
    )
    return list(rows.unique().all())


async def comments(db: AsyncSession, ticket_id: int) -> list[TicketComment]:
    rows = await db.scalars(
        select(TicketComment).where(TicketComment.ticket_id == ticket_id).order_by(TicketComment.id)
    )
    return list(rows.unique().all())


async def attachments(db: AsyncSession, ticket_id: int) -> list[TicketAttachment]:
    rows = await db.scalars(
        select(TicketAttachment).where(TicketAttachment.ticket_id == ticket_id).order_by(TicketAttachment.id)
    )
    return list(rows.unique().all())


async def attachment(db: AsyncSession, ticket_id: int, attachment_id: int) -> TicketAttachment | None:
    return await db.scalar(
        select(TicketAttachment).where(TicketAttachment.id == attachment_id, TicketAttachment.ticket_id == ticket_id)
    )


# ------------------------------------------------------------------------------------------------ customers & agents
async def customer_by_code(db: AsyncSession, code: str) -> Customer | None:
    return await db.scalar(select(Customer).where(Customer.customer_code == code.strip().upper()))


async def add_customer(db: AsyncSession, customer: Customer) -> Customer:
    db.add(customer)
    await db.flush()
    await db.refresh(customer)
    return customer


async def active_agent(db: AsyncSession, user_id: int) -> User | None:
    return await db.scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))


async def open_load(db: AsyncSession, user_ids: list[int], open_statuses: list[str]) -> dict[int, int]:
    """Open tickets currently assigned to each user."""
    if not user_ids:
        return {}
    rows = await db.execute(
        select(Ticket.assignee_id, func.count())
        .where(and_(Ticket.assignee_id.in_(user_ids), Ticket.status.in_(open_statuses)))
        .group_by(Ticket.assignee_id)
    )
    return {uid: n for uid, n in rows.all()}


async def waiting_dead_letter_consumers(db: AsyncSession, ticket_id: int) -> set[str]:
    rows = await db.scalars(
        select(DeadLetter.consumer).where(DeadLetter.ticket_id == ticket_id, DeadLetter.status == "waiting")
    )
    return set(rows.all())
