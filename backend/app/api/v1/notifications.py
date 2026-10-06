"""Notifications (spec: GET /notifications · POST /notifications/{id}/read · live SSE stream). Everyone sees only
their own."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser
from app.core.db import get_session
from app.services import notifications as svc

router = APIRouter(prefix="/notifications", tags=["notifications"])
Db = Depends(get_session)


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    title: str
    message: str
    ticket_id: int | None
    severity: str
    read_at: datetime | None
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    total: int
    page: int
    page_size: int
    unread: int


class Preferences(BaseModel):
    email: bool


@router.get("", response_model=NotificationPage)
async def list_notifications(
    user: CurrentUser,
    db: AsyncSession = Db,
    unread: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> NotificationPage:
    items, total, unread_count = await svc.list_for(db, user, unread_only=unread, page=page, page_size=page_size)
    return NotificationPage(
        items=[NotificationOut.model_validate(n) for n in items],
        total=total,
        page=page,
        page_size=page_size,
        unread=unread_count,
    )


@router.post("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(notification_id: int, user: CurrentUser, db: AsyncSession = Db) -> NotificationOut:
    return NotificationOut.model_validate(await svc.mark_read(db, user, notification_id))


@router.post("/read-all")
async def mark_all_read(user: CurrentUser, db: AsyncSession = Db) -> dict[str, int]:
    return {"marked": await svc.mark_all_read(db, user)}


@router.get("/preferences", response_model=Preferences)
async def get_preferences(user: CurrentUser) -> Preferences:
    return Preferences(email=user.email_notifications)


@router.put("/preferences", response_model=Preferences)
async def set_preferences(body: Preferences, user: CurrentUser, db: AsyncSession = Db) -> Preferences:
    user.email_notifications = body.email
    db.add(user)
    await db.commit()
    return Preferences(email=user.email_notifications)


@router.get("/stream")
async def stream(request: Request, user: CurrentUser, db: AsyncSession = Db) -> StreamingResponse:
    """Server-Sent Events: `ready` with the unread count, then `notification` and `unread` events live. The browser
    reads it with fetch streaming, so the access token travels in the Authorization header, never in the URL."""
    unread = await svc.unread_count(db, user)
    await db.close()  # don't hold a database connection for the life of the stream
    return StreamingResponse(
        svc.stream(user, unread, is_disconnected=request.is_disconnected),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
