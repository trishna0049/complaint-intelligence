"""SLA policies (spec: CRUD /sla-policies, Admin)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AdminUser
from app.core.db import get_session
from app.schemas.sla import SlaPolicyIn, SlaPolicyOut, SlaPolicyUpdate
from app.services import sla_policies as svc

router = APIRouter(prefix="/sla-policies", tags=["sla"])
Db = Depends(get_session)


@router.get("", response_model=list[SlaPolicyOut])
async def list_policies(_: AdminUser, db: AsyncSession = Db) -> list[SlaPolicyOut]:
    return [SlaPolicyOut.model_validate(p) for p in await svc.list_policies(db)]


@router.post("", response_model=SlaPolicyOut, status_code=status.HTTP_201_CREATED)
async def create_policy(body: SlaPolicyIn, admin: AdminUser, db: AsyncSession = Db) -> SlaPolicyOut:
    return SlaPolicyOut.model_validate(await svc.create(db, admin, body))


@router.patch("/{policy_id}", response_model=SlaPolicyOut)
async def update_policy(policy_id: int, body: SlaPolicyUpdate, admin: AdminUser, db: AsyncSession = Db) -> SlaPolicyOut:
    return SlaPolicyOut.model_validate(await svc.update(db, admin, policy_id, body))


@router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(policy_id: int, admin: AdminUser, db: AsyncSession = Db) -> None:
    await svc.delete(db, admin, policy_id)
