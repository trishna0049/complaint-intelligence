"""Queries for users, teams, departments, categories, refresh tokens and audit logs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Category, Department, RefreshToken, Team, User


# ------------------------------------------------------------------------------------------------ users
async def get(db: AsyncSession, user_id: int) -> User | None:
    return await db.get(User, user_id)


async def by_email(db: AsyncSession, email: str) -> User | None:
    return await db.scalar(select(User).where(User.email == email.strip().lower()))


async def search(
    db: AsyncSession,
    *,
    q: str | None = None,
    role: str | None = None,
    team_id: int | None = None,
    active: bool | None = None,
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[User], int]:
    stmt = select(User)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.name.ilike(like), User.email.ilike(like)))
    if role:
        stmt = stmt.where(User.role == role)
    if team_id:
        stmt = stmt.where(User.team_id == team_id)
    if active is not None:
        stmt = stmt.where(User.is_active.is_(active))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = await db.scalars(
        stmt.order_by(User.role, User.name, User.id).limit(page_size).offset((page - 1) * page_size)
    )
    return list(rows.unique().all()), total


async def count_by_team(db: AsyncSession) -> dict[int, int]:
    rows = await db.execute(
        select(User.team_id, func.count())
        .where(User.is_active.is_(True), User.team_id.is_not(None))
        .group_by(User.team_id)
    )
    return {team_id: n for team_id, n in rows.all()}


async def count_active_admins(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).where(User.role == "ADMIN", User.is_active.is_(True))) or 0


# ------------------------------------------------------------------------------------------------ org
async def list_departments(db: AsyncSession) -> list[Department]:
    return list((await db.scalars(select(Department).order_by(Department.name))).all())


async def get_department(db: AsyncSession, department_id: int) -> Department | None:
    return await db.get(Department, department_id)


async def list_teams(db: AsyncSession) -> list[Team]:
    return list((await db.scalars(select(Team).order_by(Team.name))).unique().all())


async def get_team(db: AsyncSession, team_id: int) -> Team | None:
    return await db.get(Team, team_id)


async def team_by_name(db: AsyncSession, name: str) -> Team | None:
    return await db.scalar(select(Team).where(func.lower(Team.name) == name.strip().lower()))


async def list_categories(db: AsyncSession) -> list[Category]:
    return list((await db.scalars(select(Category).order_by(Category.name))).unique().all())


async def get_category(db: AsyncSession, category_id: int) -> Category | None:
    return await db.get(Category, category_id)


async def category_by_name(db: AsyncSession, name: str) -> Category | None:
    return await db.scalar(select(Category).where(func.lower(Category.name) == name.strip().lower()))


async def count_categories_for_team(db: AsyncSession, team_id: int) -> int:
    return await db.scalar(select(func.count()).where(Category.team_id == team_id)) or 0


# ------------------------------------------------------------------------------------------------ refresh tokens
async def token_by_hash(db: AsyncSession, token_hash: str, *, for_update: bool = False) -> RefreshToken | None:
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    if for_update:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt)


async def revoke_family(db: AsyncSession, family_id: uuid.UUID, reason: str, now: datetime) -> int:
    result = await db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked.is_(False))
        .values(revoked=True, revoked_at=now, revoked_reason=reason)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def revoke_all_for_user(db: AsyncSession, user_id: int, reason: str, now: datetime) -> int:
    result = await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False))
        .values(revoked=True, revoked_at=now, revoked_reason=reason)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


# ------------------------------------------------------------------------------------------------ audit
def audit(
    db: AsyncSession,
    action: str,
    *,
    actor_id: int | None,
    resource_type: str | None = None,
    resource_id: Any = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Stage an audit row in the caller's transaction (it commits together with the change it describes)."""
    row = AuditLog(
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=None if resource_id is None else str(resource_id),
        metadata_=metadata,
    )
    db.add(row)
    return row


async def list_audit(db: AsyncSession, *, limit: int = 100) -> list[AuditLog]:
    return list((await db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))).all())
