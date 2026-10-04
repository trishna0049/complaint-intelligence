"""Password hashing (argon2id), access tokens (JWT) and refresh-token helpers."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()  # argon2id, 64 MiB, t=3, p=4 (library defaults, RFC 9106 "second recommended")
# Verified against when the e-mail is unknown, so a login takes the same time whether or not the account exists.
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


# ------------------------------------------------------------------------------------------------ access tokens
@dataclass(frozen=True)
class AccessClaims:
    user_id: int
    role: str
    expires_at: datetime


class InvalidToken(Exception):
    pass


def create_access_token(user_id: int, role: str, now: datetime | None = None) -> tuple[str, int]:
    """Return (token, lifetime in seconds)."""
    s = get_settings()
    now = now or datetime.now(UTC)
    lifetime = s.access_token_minutes * 60
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=lifetime)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm), lifetime


def decode_access_token(token: str) -> AccessClaims:
    s = get_settings()
    try:
        payload = jwt.decode(
            token, s.jwt_secret, algorithms=[s.jwt_algorithm], options={"require": ["sub", "exp", "iat", "type"]}
        )
    except jwt.ExpiredSignatureError as exc:
        raise InvalidToken("expired") from exc
    except jwt.PyJWTError as exc:
        raise InvalidToken("invalid") from exc
    if payload.get("type") != "access":
        raise InvalidToken("wrong token type")
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError) as exc:
        raise InvalidToken("invalid subject") from exc
    return AccessClaims(user_id, str(payload.get("role")), datetime.fromtimestamp(payload["exp"], UTC))


# ------------------------------------------------------------------------------------------------ refresh tokens
def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
