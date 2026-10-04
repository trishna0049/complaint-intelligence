"""FastAPI dependencies that authenticate the caller and enforce roles.

Every non-public route depends on `current_user` (tests/backend/test_auth.py fails if one does not). The user is
re-loaded on each request, so a deactivated account or a changed role takes effect immediately.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import InvalidToken, decode_access_token
from app.core.db import get_session
from app.models import User
from app.repositories import users as users_repo

_bearer = HTTPBearer(auto_error=False, description="Access token from POST /api/v1/auth/login")


def _unauthorized(message: str, code: str = "not_authenticated") -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail={"code": code, "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


async def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("Sign in to continue.")
    try:
        claims = decode_access_token(credentials.credentials)
    except InvalidToken as exc:
        code = "token_expired" if str(exc) == "expired" else "invalid_token"
        raise _unauthorized(
            "Your session has expired. Sign in again." if code == "token_expired" else "Invalid access token.", code
        ) from exc
    user = await users_repo.get(db, claims.user_id)
    if user is None or not user.is_active:
        raise _unauthorized("This account is not active.", "inactive_account")
    return user


async def require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != "ADMIN":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail={"code": "forbidden", "message": "This action needs the Admin role."}
        )
    return user


CurrentUser = Annotated[User, Depends(current_user)]
AdminUser = Annotated[User, Depends(require_admin)]
