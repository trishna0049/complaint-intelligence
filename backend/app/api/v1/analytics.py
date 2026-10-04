"""Analytics (admin dashboard). Agents see "My stats" instead (spec: analytics dashboard is Admin only)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AdminUser
from app.core.db import get_session
from app.services import analytics as svc

router = APIRouter(prefix="/analytics", tags=["analytics"])

Days = Query(default=30, ge=7, le=365)


@router.get("/overview")
async def overview(_: AdminUser, days: int = Days, db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """KPIs vs the previous period, open high-priority tickets and plain-English insights."""
    return await svc.overview(db, days)


@router.get("/trends")
async def trends(
    _: AdminUser,
    days: int = Days,
    granularity: str = Query(default="day", pattern="^(day|week|month)$"),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Volume, sentiment mix, high-priority volume and CSAT per day, week or month."""
    return await svc.trends(db, days, granularity)


@router.get("/categories")
async def categories(_: AdminUser, days: int = Days, db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Breakdowns by category, intent, channel, priority and sentiment."""
    return await svc.categories(db, days)


@router.get("/emerging")
async def emerging(_: AdminUser, db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Week-over-week growth per category."""
    return await svc.emerging(db)
