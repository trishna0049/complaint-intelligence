"""Admin-only management: users, teams, departments, categories (writes) and the audit log.

Categories can be *read* by every signed-in user (forms and filters need them); every write is Admin only.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AdminUser, CurrentUser
from app.core.db import get_session
from app.repositories import users as users_repo
from app.schemas.auth import (
    AuditOut,
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    DepartmentCreate,
    DepartmentOut,
    TeamCreate,
    TeamOut,
    TeamUpdate,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.schemas.common import Page
from app.schemas.events import DeadLetterOut, DiscardRequest, PipelineStatus
from app.services import admin as svc
from app.services import events_admin as events_svc

Db = Depends(get_session)

users = APIRouter(prefix="/users", tags=["admin: users"])
teams = APIRouter(prefix="/teams", tags=["admin: teams"])
departments = APIRouter(prefix="/departments", tags=["admin: teams"])
categories = APIRouter(prefix="/categories", tags=["categories"])
audit = APIRouter(prefix="/admin/audit-logs", tags=["admin: audit"])


# ------------------------------------------------------------------------------------------------ users
@users.get("", response_model=Page[UserOut])
async def list_users(
    _: AdminUser,
    db: AsyncSession = Db,
    q: str | None = Query(default=None, max_length=200),
    role: str | None = Query(default=None, pattern="^(ADMIN|AGENT)$"),
    team_id: int | None = None,
    active: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
) -> Page[UserOut]:
    items, total = await svc.list_users(
        db, q=q, role=role, team_id=team_id, active=active, page=page, page_size=page_size
    )
    return Page(items=[UserOut.model_validate(u) for u in items], total=total, page=page, page_size=page_size)


@users.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, admin: AdminUser, db: AsyncSession = Db) -> UserOut:
    return UserOut.model_validate(await svc.create_user(db, admin, body))


@users.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: int, _: AdminUser, db: AsyncSession = Db) -> UserOut:
    return UserOut.model_validate(await svc.get_user(db, user_id))


@users.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: int, body: UserUpdate, admin: AdminUser, db: AsyncSession = Db) -> UserOut:
    return UserOut.model_validate(await svc.update_user(db, admin, user_id, body))


@users.delete("/{user_id}", response_model=UserOut)
async def deactivate_user(user_id: int, admin: AdminUser, db: AsyncSession = Db) -> UserOut:
    """Users are deactivated, never deleted, so their ticket history and audit trail stay intact."""
    return UserOut.model_validate(await svc.update_user(db, admin, user_id, UserUpdate(is_active=False)))


# ------------------------------------------------------------------------------------------------ teams
@teams.get("", response_model=list[TeamOut])
async def list_teams(_: CurrentUser, db: AsyncSession = Db) -> list[TeamOut]:
    """Readable by agents too (team pickers); member counts included."""
    return await svc.team_views(db)


@teams.get("/{team_id}/members")
async def team_members(team_id: int, user: CurrentUser, db: AsyncSession = Db) -> list[dict[str, Any]]:
    """Active members and their open tickets. Agents: own team only."""
    return await svc.team_members(db, user, team_id)


@teams.post("", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
async def create_team(body: TeamCreate, admin: AdminUser, db: AsyncSession = Db) -> TeamOut:
    return await svc.create_team(db, admin, body)


@teams.patch("/{team_id}", response_model=TeamOut)
async def update_team(team_id: int, body: TeamUpdate, admin: AdminUser, db: AsyncSession = Db) -> TeamOut:
    return await svc.update_team(db, admin, team_id, body)


@teams.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(team_id: int, admin: AdminUser, db: AsyncSession = Db) -> None:
    await svc.delete_team(db, admin, team_id)


@departments.get("", response_model=list[DepartmentOut])
async def list_departments(_: AdminUser, db: AsyncSession = Db) -> list[DepartmentOut]:
    return [DepartmentOut.model_validate(d) for d in await svc.list_departments(db)]


@departments.post("", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
async def create_department(body: DepartmentCreate, admin: AdminUser, db: AsyncSession = Db) -> DepartmentOut:
    return DepartmentOut.model_validate(await svc.create_department(db, admin, body))


# ------------------------------------------------------------------------------------------------ categories
@categories.get("", response_model=list[CategoryOut])
async def list_categories(_: CurrentUser, db: AsyncSession = Db) -> list[CategoryOut]:
    return await svc.list_categories(db)


@categories.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(body: CategoryCreate, admin: AdminUser, db: AsyncSession = Db) -> CategoryOut:
    return await svc.create_category(db, admin, body)


@categories.patch("/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: int, body: CategoryUpdate, admin: AdminUser, db: AsyncSession = Db
) -> CategoryOut:
    return await svc.update_category(db, admin, category_id, body)


@categories.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(category_id: int, admin: AdminUser, db: AsyncSession = Db) -> None:
    await svc.delete_category(db, admin, category_id)


# ------------------------------------------------------------------------------------------------ audit
@audit.get("", response_model=list[AuditOut])
async def list_audit_logs(
    _: AdminUser, db: AsyncSession = Db, limit: int = Query(default=100, ge=1, le=500)
) -> list[AuditOut]:
    return [AuditOut.model_validate(a) for a in await users_repo.list_audit(db, limit=limit)]


# ------------------------------------------------------------------------------------------------ events / DLQ
events = APIRouter(prefix="/admin", tags=["admin: events"])


@events.get("/events", response_model=PipelineStatus)
async def pipeline_status(_: AdminUser, db: AsyncSession = Db) -> PipelineStatus:
    """Outbox lag, events processed per worker and dead letters waiting."""
    return PipelineStatus.model_validate(await events_svc.pipeline_status(db))


@events.get("/dlq", response_model=Page[DeadLetterOut])
async def list_dead_letters(
    _: AdminUser,
    db: AsyncSession = Db,
    status: str | None = Query(default="waiting", pattern="^(waiting|replayed|discarded)$"),
    consumer: str | None = Query(default=None, max_length=48),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> Page[DeadLetterOut]:
    items, total = await events_svc.list_dead_letters(
        db, state=status, consumer=consumer, page=page, page_size=page_size
    )
    return Page(items=[DeadLetterOut.model_validate(d) for d in items], total=total, page=page, page_size=page_size)


@events.post("/dlq/{letter_id}/replay", response_model=DeadLetterOut)
async def replay_dead_letter(letter_id: int, admin: AdminUser, db: AsyncSession = Db) -> DeadLetterOut:
    """Publish the event again (same event id): only the consumer that failed processes it."""
    return DeadLetterOut.model_validate(await events_svc.replay(db, admin, letter_id))


@events.post("/dlq/{letter_id}/discard", response_model=DeadLetterOut)
async def discard_dead_letter(
    letter_id: int, body: DiscardRequest, admin: AdminUser, db: AsyncSession = Db
) -> DeadLetterOut:
    return DeadLetterOut.model_validate(await events_svc.discard(db, admin, letter_id, body.reason))
