"""Login, refresh-token rotation with reuse detection, and logout."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    needs_rehash,
    new_refresh_token,
    verify_password,
)
from app.core.config import get_settings
from app.models import RefreshToken, User
from app.repositories import users as repo


@dataclass
class Session:
    user: User
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_at: datetime


def _error(code: str, message: str, http: int = status.HTTP_401_UNAUTHORIZED) -> HTTPException:
    return HTTPException(http, detail={"code": code, "message": message})


async def _issue(db: AsyncSession, user: User, family_id: uuid.UUID | None, now: datetime) -> tuple[RefreshToken, str]:
    raw = new_refresh_token()
    token = RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(raw),
        family_id=family_id or uuid.uuid4(),
        expires_at=now + timedelta(days=get_settings().refresh_token_days),
    )
    db.add(token)
    await db.flush()
    return token, raw


async def login(db: AsyncSession, email: str, password: str) -> Session:
    now = datetime.now(UTC)
    user = await repo.by_email(db, email)
    # verify_password also runs for unknown e-mails, so timing does not reveal which accounts exist.
    ok = verify_password(user.password_hash if user else None, password)
    if not ok or user is None or not user.is_active:
        repo.audit(
            db,
            "auth.login_failed",
            actor_id=user.id if user else None,
            resource_type="user",
            resource_id=user.id if user else None,
            metadata={"email": email.strip().lower()[:255], "reason": "inactive" if ok and user else "bad_credentials"},
        )
        await db.commit()
        raise _error("invalid_credentials", "Invalid email or password.")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = now
    refresh, raw = await _issue(db, user, None, now)
    repo.audit(db, "auth.login", actor_id=user.id, resource_type="user", resource_id=user.id)
    await db.commit()
    access, lifetime = create_access_token(user.id, user.role, now)
    return Session(user, access, lifetime, raw, refresh.expires_at)


async def refresh(db: AsyncSession, raw_token: str | None) -> Session:
    """Rotate: revoke the presented token and issue a new one in the same family.

    Presenting a token that was already rotated means it was copied (theft) — unless it happens within a few seconds
    of the rotation, which is two tabs refreshing at once; that returns 409 and the client retries with the newer
    cookie. Real reuse revokes every token in the family, ending that login everywhere.
    """
    if not raw_token:
        raise _error("no_refresh_token", "Sign in to continue.")
    now = datetime.now(UTC)
    s = get_settings()
    token = await repo.token_by_hash(db, hash_refresh_token(raw_token), for_update=True)
    if token is None:
        raise _error("invalid_refresh_token", "Sign in to continue.")
    if token.revoked:
        rotated_recently = (
            token.revoked_reason == "rotated"
            and token.revoked_at is not None
            and now - token.revoked_at < timedelta(seconds=s.refresh_reuse_leeway_seconds)
        )
        if rotated_recently:
            raise _error("refresh_race", "The session was just refreshed; retry.", status.HTTP_409_CONFLICT)
        revoked = await repo.revoke_family(db, token.family_id, "reuse_detected", now)
        repo.audit(
            db,
            "auth.refresh_reuse_detected",
            actor_id=token.user_id,
            resource_type="user",
            resource_id=token.user_id,
            metadata={"family_id": str(token.family_id), "tokens_revoked": revoked},
        )
        await db.commit()
        raise _error("refresh_token_reused", "This session was ended for security reasons. Sign in again.")
    if token.expires_at <= now:
        raise _error("refresh_token_expired", "Your session has expired. Sign in again.")
    user = await repo.get(db, token.user_id)
    if user is None or not user.is_active:
        await repo.revoke_family(db, token.family_id, "inactive_account", now)
        await db.commit()
        raise _error("inactive_account", "This account is not active.")

    new_token, raw = await _issue(db, user, token.family_id, now)
    token.revoked, token.revoked_at, token.revoked_reason = True, now, "rotated"
    token.replaced_by_id = new_token.id
    await db.commit()
    access, lifetime = create_access_token(user.id, user.role, now)
    return Session(user, access, lifetime, raw, new_token.expires_at)


async def logout(db: AsyncSession, raw_token: str | None) -> None:
    if not raw_token:
        return
    token = await repo.token_by_hash(db, hash_refresh_token(raw_token), for_update=True)
    if token is None:
        return
    await repo.revoke_family(db, token.family_id, "logout", datetime.now(UTC))
    repo.audit(db, "auth.logout", actor_id=token.user_id, resource_type="user", resource_id=token.user_id)
    await db.commit()
