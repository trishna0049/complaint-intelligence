"""Authentication: login, refresh (rotating cookie), logout, current user.

The refresh token travels only in an HttpOnly, SameSite=Strict cookie scoped to /api/v1/auth, so page scripts can't
read it; the short-lived access token is returned in the body and kept in memory by the client.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser
from app.core.config import get_settings
from app.core.db import get_session
from app.schemas.auth import LoginRequest, TokenResponse, UserOut
from app.services import auth as svc

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_PATH = "/api/v1/auth"


def _set_cookie(response: Response, session: svc.Session) -> None:
    s = get_settings()
    response.set_cookie(
        s.refresh_cookie_name,
        session.refresh_token,
        max_age=max(0, int((session.refresh_expires_at - datetime.now(UTC)).total_seconds())),
        httponly=True,
        secure=s.cookie_secure,
        samesite="strict",
        path=COOKIE_PATH,
    )


def _clear_cookie(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(
        s.refresh_cookie_name, path=COOKIE_PATH, secure=s.cookie_secure, httponly=True, samesite="strict"
    )


def _token_response(session: svc.Session) -> TokenResponse:
    return TokenResponse(
        access_token=session.access_token, expires_in=session.expires_in, user=UserOut.model_validate(session.user)
    )


def _cookie(request: Request) -> str | None:
    return request.cookies.get(get_settings().refresh_cookie_name)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, response: Response, db: AsyncSession = Depends(get_session)) -> TokenResponse:
    session = await svc.login(db, body.email, body.password)
    _set_cookie(response, session)
    return _token_response(session)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_session)) -> TokenResponse:
    """Exchange the refresh cookie for a new access token and a new (rotated) refresh cookie."""
    session = await svc.refresh(db, _cookie(request))
    _set_cookie(response, session)
    return _token_response(session)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_session)) -> None:
    await svc.logout(db, _cookie(request))
    _clear_cookie(response)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
