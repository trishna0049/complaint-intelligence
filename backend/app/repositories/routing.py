"""Queries the routing service needs: which team owns a category, and that team's agents with their open load."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.lifecycle import OPEN_STATUSES
from app.domain.routing import Candidate
from app.models import Category, Team, Ticket, User

OPEN = sorted(s.value for s in OPEN_STATUSES)
# First key of the two-key advisory lock taken per team while an agent is chosen (second key: the team id).
ROUTING_LOCK_KEY = 5_101


async def category_team(db: AsyncSession, category: str | None) -> tuple[int, str] | None:
    if not category:
        return None
    row = (
        await db.execute(
            select(Team.id, Team.name).join(Category, Category.team_id == Team.id).where(Category.name == category)
        )
    ).first()
    return (row[0], row[1]) if row else None


async def lock_team(db: AsyncSession, team_id: int) -> None:
    """Serialise routing decisions per team until the transaction ends, so two tickets created at the same moment
    can't both see the same agent as least busy."""
    await db.execute(select(func.pg_advisory_xact_lock(ROUTING_LOCK_KEY, team_id)))


async def candidates(db: AsyncSession, team_id: int) -> list[Candidate]:
    """Active agents of the team with the number of open tickets assigned to each."""
    open_count = func.count(Ticket.id)
    rows = await db.execute(
        select(User.id, User.name, User.last_assigned_at, open_count)
        .outerjoin(Ticket, and_(Ticket.assignee_id == User.id, Ticket.status.in_(OPEN)))
        .where(User.team_id == team_id, User.role == "AGENT", User.is_active.is_(True))
        .group_by(User.id)
    )
    return [Candidate(id=uid, name=name, open_tickets=n, last_assigned_at=last) for uid, name, last, n in rows.all()]


async def mark_assigned(db: AsyncSession, user_id: int, at: datetime) -> None:
    await db.execute(update(User).where(User.id == user_id).values(last_assigned_at=at))
