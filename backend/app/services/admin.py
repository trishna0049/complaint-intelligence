"""Admin management of users, teams, departments and categories. Every change is audited in the same transaction."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.priority import BASE_PRIORITY
from app.auth.security import hash_password
from app.domain.lifecycle import OPEN_STATUSES
from app.models import Category, Department, Team, User
from app.repositories import tickets as tickets_repo
from app.repositories import users as repo
from app.schemas.auth import (
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    DepartmentCreate,
    TeamCreate,
    TeamOut,
    TeamUpdate,
    UserCreate,
    UserUpdate,
)


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail={"code": "conflict", "message": message})


def _not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{what} not found")


async def _commit(db: AsyncSession, conflict_message: str) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise _conflict(conflict_message) from exc


# ------------------------------------------------------------------------------------------------ users
async def get_user(db: AsyncSession, user_id: int) -> User:
    user = await repo.get(db, user_id)
    if user is None:
        raise _not_found("User")
    return user


async def _check_team(db: AsyncSession, team_id: int | None) -> None:
    if team_id is not None and await repo.get_team(db, team_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown team")


async def create_user(db: AsyncSession, actor: User, data: UserCreate) -> User:
    await _check_team(db, data.team_id)
    if await repo.by_email(db, data.email):
        raise _conflict("A user with this email already exists.")
    user = User(
        name=data.name.strip(),
        email=data.email,
        password_hash=hash_password(data.password),
        role=data.role,
        team_id=data.team_id,
        is_active=True,
        source="app",
    )
    db.add(user)
    await db.flush()
    repo.audit(
        db,
        "user.create",
        actor_id=actor.id,
        resource_type="user",
        resource_id=user.id,
        metadata={"email": user.email, "role": user.role, "team_id": user.team_id},
    )
    await _commit(db, "A user with this email already exists.")
    await db.refresh(user)
    return user


async def update_user(db: AsyncSession, actor: User, user_id: int, data: UserUpdate) -> User:
    user = await get_user(db, user_id)
    changes: dict[str, Any] = {}
    if data.name is not None and data.name.strip() != user.name:
        changes["name"] = [user.name, data.name.strip()]
        user.name = data.name.strip()
    if data.team_id is not None or data.clear_team:
        new_team = None if data.clear_team else data.team_id
        await _check_team(db, new_team)
        if new_team != user.team_id:
            changes["team_id"] = [user.team_id, new_team]
            user.team_id = new_team
    demoting = data.role is not None and data.role != user.role and user.role == "ADMIN"
    deactivating = data.is_active is False and user.is_active and user.role == "ADMIN"
    if (demoting or deactivating) and await repo.count_active_admins(db) <= 1:
        raise _conflict("At least one active admin must remain.")
    if user.id == actor.id and (demoting or data.is_active is False):
        raise _conflict("You can't remove your own admin access.")
    if data.role is not None and data.role != user.role:
        changes["role"] = [user.role, data.role]
        user.role = data.role
    if data.is_active is not None and data.is_active != user.is_active:
        changes["is_active"] = [user.is_active, data.is_active]
        user.is_active = data.is_active
    if data.password is not None:
        changes["password"] = "reset"
        user.password_hash = hash_password(data.password)
    now = datetime.now(UTC)
    if {"role", "is_active", "password"} & changes.keys():
        # A changed role, a deactivation or a new password ends every existing session of that user.
        await repo.revoke_all_for_user(db, user.id, "admin", now)
    if changes:
        action = "user.deactivate" if changes.get("is_active") == [True, False] else "user.update"
        repo.audit(db, action, actor_id=actor.id, resource_type="user", resource_id=user.id, metadata=changes)
    await _commit(db, "Could not update the user.")
    await db.refresh(user)
    return user


async def list_users(db: AsyncSession, **filters: Any) -> tuple[list[User], int]:
    return await repo.search(db, **filters)


# ------------------------------------------------------------------------------------------------ departments
async def list_departments(db: AsyncSession) -> list[Department]:
    return await repo.list_departments(db)


async def create_department(db: AsyncSession, actor: User, data: DepartmentCreate) -> Department:
    dept = Department(name=data.name.strip())
    db.add(dept)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise _conflict("A department with this name already exists.") from exc
    repo.audit(
        db,
        "department.create",
        actor_id=actor.id,
        resource_type="department",
        resource_id=dept.id,
        metadata={"name": dept.name},
    )
    await _commit(db, "A department with this name already exists.")
    return dept


# ------------------------------------------------------------------------------------------------ teams
async def team_views(db: AsyncSession) -> list[TeamOut]:
    teams = await repo.list_teams(db)
    members = await repo.count_by_team(db)
    by_team: dict[int, list[str]] = {}
    for c in await repo.list_categories(db):
        if c.team_id:
            by_team.setdefault(c.team_id, []).append(c.name)
    return [
        TeamOut.model_validate(t).model_copy(
            update={"member_count": members.get(t.id, 0), "categories": by_team.get(t.id, [])}
        )
        for t in teams
    ]


async def team_view(db: AsyncSession, team_id: int) -> TeamOut:
    for t in await team_views(db):
        if t.id == team_id:
            return t
    raise _not_found("Team")


async def create_team(db: AsyncSession, actor: User, data: TeamCreate) -> TeamOut:
    if await repo.get_department(db, data.department_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown department")
    if await repo.team_by_name(db, data.name):
        raise _conflict("A team with this name already exists.")
    team = Team(name=data.name.strip(), department_id=data.department_id, description=data.description)
    db.add(team)
    await db.flush()
    repo.audit(
        db,
        "team.create",
        actor_id=actor.id,
        resource_type="team",
        resource_id=team.id,
        metadata={"name": team.name, "department_id": team.department_id},
    )
    await _commit(db, "A team with this name already exists.")
    return await team_view(db, team.id)


async def update_team(db: AsyncSession, actor: User, team_id: int, data: TeamUpdate) -> TeamOut:
    team = await repo.get_team(db, team_id)
    if team is None:
        raise _not_found("Team")
    changes: dict[str, Any] = {}
    if data.name is not None and data.name.strip() != team.name:
        existing = await repo.team_by_name(db, data.name)
        if existing and existing.id != team.id:
            raise _conflict("A team with this name already exists.")
        changes["name"] = [team.name, data.name.strip()]
        team.name = data.name.strip()
    if data.department_id is not None and data.department_id != team.department_id:
        if await repo.get_department(db, data.department_id) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown department")
        changes["department_id"] = [team.department_id, data.department_id]
        team.department_id = data.department_id
    if data.description is not None and data.description != team.description:
        changes["description"] = "changed"
        team.description = data.description
    if changes:
        repo.audit(db, "team.update", actor_id=actor.id, resource_type="team", resource_id=team.id, metadata=changes)
    await _commit(db, "Could not update the team.")
    return await team_view(db, team.id)


async def delete_team(db: AsyncSession, actor: User, team_id: int) -> None:
    view = await team_view(db, team_id)
    if view.member_count or view.categories:
        raise _conflict("Move the team's members and categories to another team before deleting it.")
    team = await repo.get_team(db, team_id)
    await db.delete(team)
    repo.audit(
        db, "team.delete", actor_id=actor.id, resource_type="team", resource_id=team_id, metadata={"name": view.name}
    )
    await _commit(db, "The team is still referenced and can't be deleted.")


# ------------------------------------------------------------------------------------------------ categories
def category_view(c: Category) -> CategoryOut:
    return CategoryOut.model_validate(c).model_copy(
        update={"base_priority": BASE_PRIORITY.get(c.name, "Medium"), "builtin": c.name in BASE_PRIORITY}
    )


async def list_categories(db: AsyncSession) -> list[CategoryOut]:
    return [category_view(c) for c in await repo.list_categories(db)]


async def create_category(db: AsyncSession, actor: User, data: CategoryCreate) -> CategoryOut:
    await _check_team(db, data.team_id)
    if await repo.category_by_name(db, data.name):
        raise _conflict("A category with this name already exists.")
    cat = Category(name=data.name.strip(), description=data.description, team_id=data.team_id)
    db.add(cat)
    await db.flush()
    repo.audit(
        db,
        "category.create",
        actor_id=actor.id,
        resource_type="category",
        resource_id=cat.id,
        metadata={"name": cat.name, "team_id": cat.team_id},
    )
    await _commit(db, "A category with this name already exists.")
    await db.refresh(cat)
    return category_view(cat)


async def update_category(db: AsyncSession, actor: User, category_id: int, data: CategoryUpdate) -> CategoryOut:
    cat = await repo.get_category(db, category_id)
    if cat is None:
        raise _not_found("Category")
    changes: dict[str, Any] = {}
    if data.name is not None and data.name.strip() != cat.name:
        if cat.name in BASE_PRIORITY:
            raise _conflict(f"'{cat.name}' is a built-in category: the classifier and the priority rules use its name.")
        existing = await repo.category_by_name(db, data.name)
        if existing and existing.id != cat.id:
            raise _conflict("A category with this name already exists.")
        changes["name"] = [cat.name, data.name.strip()]
        cat.name = data.name.strip()
    if data.description is not None and data.description != cat.description:
        changes["description"] = "changed"
        cat.description = data.description
    if data.team_id is not None or data.clear_team:
        new_team = None if data.clear_team else data.team_id
        await _check_team(db, new_team)
        if new_team != cat.team_id:
            changes["team_id"] = [cat.team_id, new_team]
            cat.team_id = new_team
    if changes:
        repo.audit(
            db, "category.update", actor_id=actor.id, resource_type="category", resource_id=cat.id, metadata=changes
        )
    await _commit(db, "Could not update the category.")
    await db.refresh(cat)
    return category_view(cat)


async def delete_category(db: AsyncSession, actor: User, category_id: int) -> None:
    cat = await repo.get_category(db, category_id)
    if cat is None:
        raise _not_found("Category")
    if cat.name in BASE_PRIORITY:
        raise _conflict(f"'{cat.name}' is a built-in category: the classifier and the priority rules use its name.")
    name = cat.name
    await db.delete(cat)
    repo.audit(
        db,
        "category.delete",
        actor_id=actor.id,
        resource_type="category",
        resource_id=category_id,
        metadata={"name": name},
    )
    await _commit(db, "The category is still referenced and can't be deleted.")


# ------------------------------------------------------------------------------------------------ team members
async def team_members(db: AsyncSession, actor: User, team_id: int) -> list[dict[str, Any]]:
    """Active members of a team with their open-ticket load (assignment picker; routing shows the same numbers).
    Agents may only list their own team."""
    if await repo.get_team(db, team_id) is None:
        raise _not_found("Team")
    if actor.role != "ADMIN" and actor.team_id != team_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail={"code": "forbidden", "message": "You can only list your own team."}
        )
    members, _ = await repo.search(db, team_id=team_id, active=True, page_size=10_000)
    load = await tickets_repo.open_load(db, [m.id for m in members], [s.value for s in OPEN_STATUSES])
    return [{"id": m.id, "name": m.name, "role": m.role, "open_tickets": load.get(m.id, 0)} for m in members]
