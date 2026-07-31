"""Password hashing and access tokens."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.config import Settings

_hasher = PasswordHasher()

ALGORITHM = "HS256"
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"


class AuthError(Exception):
    """Credentials or token could not be accepted."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _encode(*, settings: Settings, subject: uuid.UUID, token_type: str, lifetime: timedelta) -> str:
    issued_at = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": issued_at,
        "exp": issued_at + lifetime,
        # A unique id per token so revocation can be added without reissuing the
        # whole scheme.
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def create_access_token(settings: Settings, subject: uuid.UUID) -> str:
    return _encode(
        settings=settings,
        subject=subject,
        token_type=TOKEN_TYPE_ACCESS,
        lifetime=timedelta(minutes=settings.jwt_access_ttl_minutes),
    )


def create_refresh_token(settings: Settings, subject: uuid.UUID) -> str:
    return _encode(
        settings=settings,
        subject=subject,
        token_type=TOKEN_TYPE_REFRESH,
        lifetime=timedelta(days=settings.jwt_refresh_ttl_days),
    )


def decode_token(settings: Settings, token: str, *, expected_type: str) -> uuid.UUID:
    """Return the subject, or raise `AuthError`.

    The token type is checked explicitly so a refresh token cannot be presented as
    an access token.
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise AuthError(f"Invalid token: {exc}") from exc

    if payload.get("type") != expected_type:
        raise AuthError(f"Expected a {expected_type} token")

    try:
        return uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise AuthError("Token subject is missing or malformed") from exc
