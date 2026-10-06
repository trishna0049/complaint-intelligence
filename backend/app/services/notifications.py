"""Notifications: written by the notification worker, delivered in real time over Server-Sent Events (Redis pub/sub
fans them out to every API process a user is connected to) and, optionally, by e-mail.

Who gets what (spec: "Receive escalation and SLA-breach alerts — Admin"; "sla.warning — alerts agent"):
    ticket.assigned  -> the new assignee (not when they took it themselves)
    ticket.escalated -> every active Admin (not the one who escalated)
    sla.warning      -> the assignee (or, for an unassigned ticket, the Admins)
    sla.breached     -> every active Admin and the assignee
E-mail goes out for escalations and SLA alerts when SMTP is configured and the user hasn't opted out.
"""

from __future__ import annotations

import asyncio
import json
import logging
import smtplib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.redis import channel, get_redis
from app.events.consumer import after_commit
from app.models import Notification, Ticket, User

log = logging.getLogger("app.notifications")
EMAIL_TYPES = {"ticket_escalated", "sla_warning", "sla_breached"}
KEEPALIVE = ": keep-alive\n\n"  # an SSE comment line


def _now() -> datetime:
    return datetime.now(UTC)


def user_channel(user_id: int) -> str:
    return channel(f"notifications:{user_id}")


def as_json(n: Notification) -> dict[str, Any]:
    return {
        "id": n.id,
        "type": n.type,
        "title": n.title,
        "message": n.message,
        "ticket_id": n.ticket_id,
        "severity": n.severity,
        "read_at": n.read_at.isoformat() if n.read_at else None,
        "created_at": n.created_at.isoformat() if n.created_at else _now().isoformat(),
    }


# ------------------------------------------------------------------------------------------------ recipients
async def active_admins(db: AsyncSession) -> list[User]:
    return list((await db.scalars(select(User).where(User.role == "ADMIN", User.is_active.is_(True)))).unique().all())


async def active_user(db: AsyncSession, user_id: int | None) -> User | None:
    if user_id is None:
        return None
    user = await db.get(User, user_id)
    return user if user is not None and user.is_active else None


# ------------------------------------------------------------------------------------------------ create + deliver
async def notify(
    db: AsyncSession,
    recipients: list[User],
    *,
    type: str,
    title: str,
    message: str,
    ticket: Ticket | None,
    severity: str = "info",
) -> list[Notification]:
    """Stage one notification per recipient (deduplicated) in the caller's transaction; after it commits they are
    published to the users' live streams and, for alert types, e-mailed."""
    rows: list[Notification] = []
    seen: set[int] = set()
    for user in recipients:
        if user.id in seen:
            continue
        seen.add(user.id)
        n = Notification(
            user_id=user.id,
            type=type,
            title=title,
            message=message,
            ticket_id=ticket.id if ticket else None,
            severity=severity,
        )
        db.add(n)
        rows.append(n)
    if not rows:
        return rows
    await db.flush()
    emails = {u.id: u.email for u in recipients if u.email and u.email_notifications} if type in EMAIL_TYPES else {}

    async def deliver() -> None:
        await publish(rows)
        if emails and get_settings().smtp_host:
            await email(rows, emails)

    after_commit(db, deliver)
    return rows


async def publish(rows: list[Notification]) -> None:
    r = get_redis()
    for n in rows:
        try:
            await r.publish(user_channel(n.user_id), json.dumps({"kind": "notification", "notification": as_json(n)}))
        except Exception:  # the row is saved; the bell catches up on its next fetch
            log.warning("could not publish notification %s", n.id, exc_info=True)


def _send(to: str, subject: str, body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
        if s.smtp_starttls:
            smtp.starttls()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)


async def email(rows: list[Notification], addresses: dict[int, str]) -> None:
    base = get_settings().app_base_url.rstrip("/")
    for n in rows:
        to = addresses.get(n.user_id)
        if not to:
            continue
        link = f"{base}/tickets/{n.ticket_id}" if n.ticket_id else base
        body = f"{n.message}\n\nOpen the ticket: {link}\n\n— Complaint Intelligence (you can turn these e-mails off)"
        error: str | None = None
        try:
            await asyncio.to_thread(_send, to, n.title, body)
        except Exception as exc:  # e-mail is best effort; the in-app notification already exists
            error = f"{type(exc).__name__}: {exc}"[:500]
            log.warning("e-mail for notification %s failed: %s", n.id, error)
        async with SessionLocal() as db:
            await db.execute(
                update(Notification)
                .where(Notification.id == n.id)
                .values(emailed_at=None if error else _now(), email_error=error)
            )
            await db.commit()


# ------------------------------------------------------------------------------------------------ reading
async def list_for(
    db: AsyncSession, user: User, *, unread_only: bool, page: int, page_size: int
) -> tuple[list[Notification], int, int]:
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = await db.scalars(
        stmt.order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    return list(rows.all()), total, await unread_count(db, user)


async def unread_count(db: AsyncSession, user: User) -> int:
    return (
        await db.scalar(select(func.count()).where(Notification.user_id == user.id, Notification.read_at.is_(None)))
        or 0
    )


async def _changed(user: User, unread: int) -> None:
    try:  # every open tab of this user updates its badge
        await get_redis().publish(user_channel(user.id), json.dumps({"kind": "unread", "unread": unread}))
    except Exception:
        log.warning("could not publish unread count", exc_info=True)


async def mark_read(db: AsyncSession, user: User, notification_id: int) -> Notification:
    n = await db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:  # someone else's: as if it didn't exist
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Notification not found")
    if n.read_at is None:
        n.read_at = _now()
        await db.commit()
        await _changed(user, await unread_count(db, user))
    return n


async def mark_all_read(db: AsyncSession, user: User) -> int:
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=_now())
    )
    await db.commit()
    await _changed(user, 0)
    return result.rowcount or 0


# ------------------------------------------------------------------------------------------------ live stream
def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def stream(user: User, unread: int, *, is_disconnected=None) -> AsyncIterator[str]:
    """Server-Sent Events for one signed-in user: `ready` (unread count), then `notification` / `unread` as they
    happen, and a comment heartbeat so proxies keep the connection open."""
    s = get_settings()
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(user_channel(user.id))
    await pubsub.get_message(timeout=1)  # the subscribe confirmation
    loop = asyncio.get_running_loop()
    try:
        yield sse("ready", {"unread": unread})
        last_sent = loop.time()
        while True:
            if is_disconnected is not None and await is_disconnected():
                return
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=s.sse_heartbeat_seconds)
            if message is None:
                if loop.time() - last_sent >= s.sse_heartbeat_seconds:
                    yield KEEPALIVE
                    last_sent = loop.time()
                continue
            payload = json.loads(message["data"])
            if payload.get("kind") == "notification":
                yield sse("notification", payload["notification"])
            elif payload.get("kind") == "unread":
                yield sse("unread", {"unread": payload["unread"]})
            last_sent = loop.time()
    finally:
        await pubsub.unsubscribe(user_channel(user.id))
        await pubsub.aclose()
