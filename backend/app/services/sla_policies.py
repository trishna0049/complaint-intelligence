"""Admin management of SLA policies. One active-or-not policy per (priority, category); the category-less policy is
the priority's default and can't be deleted (every triaged ticket needs a target). A changed target applies to
clocks started from then on; running clocks keep the target they started with."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.priority import BASE_PRIORITY
from app.models import SlaPolicy, User
from app.repositories import users as users_repo
from app.schemas.sla import SlaPolicyIn, SlaPolicyUpdate

PRIORITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
# The defaults (also seeded by migration 0009): the spec's example gives a Critical ticket a 2-hour SLA.
DEFAULT_POLICIES = [
    ("Critical — 2 hours", "Critical", 120),
    ("High — 8 hours", "High", 480),
    ("Medium — 24 hours", "Medium", 1440),
    ("Low — 3 days", "Low", 4320),
]


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail={"code": "conflict", "message": message})


async def list_policies(db: AsyncSession) -> list[SlaPolicy]:
    rows = (await db.scalars(select(SlaPolicy))).all()
    return sorted(rows, key=lambda p: (PRIORITY_ORDER.get(p.priority, 9), p.category is not None, p.category or ""))


async def get(db: AsyncSession, policy_id: int) -> SlaPolicy:
    p = await db.get(SlaPolicy, policy_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="SLA policy not found")
    return p


async def _save(db: AsyncSession) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise _conflict("A policy for this priority and category already exists.") from exc


async def create(db: AsyncSession, admin: User, data: SlaPolicyIn) -> SlaPolicy:
    if data.category and data.category not in BASE_PRIORITY:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown category")
    p = SlaPolicy(**data.model_dump() | {"category": data.category or None})
    db.add(p)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise _conflict("A policy for this priority and category already exists.") from exc
    users_repo.audit(
        db,
        "sla_policy.create",
        actor_id=admin.id,
        resource_type="sla_policy",
        resource_id=p.id,
        metadata=data.model_dump(),
    )
    await _save(db)
    await db.refresh(p)
    return p


async def update(db: AsyncSession, admin: User, policy_id: int, data: SlaPolicyUpdate) -> SlaPolicy:
    p = await get(db, policy_id)
    changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None and getattr(p, k) != v}
    if not changes:
        return p
    if changes.get("is_active") is False and p.category is None:
        raise _conflict("The default policy of a priority can't be deactivated — change its target instead.")
    before = {k: getattr(p, k) for k in changes}
    for k, v in changes.items():
        setattr(p, k, v)
    users_repo.audit(
        db,
        "sla_policy.update",
        actor_id=admin.id,
        resource_type="sla_policy",
        resource_id=p.id,
        metadata={"before": before, "after": changes},
    )
    await _save(db)
    await db.refresh(p)
    return p


async def delete(db: AsyncSession, admin: User, policy_id: int) -> None:
    p = await get(db, policy_id)
    if p.category is None:
        raise _conflict("The default policy of a priority can't be deleted.")
    users_repo.audit(
        db,
        "sla_policy.delete",
        actor_id=admin.id,
        resource_type="sla_policy",
        resource_id=p.id,
        metadata={"name": p.name, "priority": p.priority, "category": p.category},
    )
    await db.delete(p)
    await db.commit()
