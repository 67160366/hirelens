"""Password hashing and access tokens."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class TokenClaims:
    """What a verified token says about itself.

    `decode_token` used to return the subject alone and drop everything else on the
    floor — including the `jti` that has been in every token since M1 specifically so
    revocation could be added later. Revoking a token needs three of these: which
    token (`jti`), whose (`subject`), and how long the revocation has to be
    remembered (`expires_at`, after which the token is dead on its own).
    """

    subject: uuid.UUID
    jti: str
    token_type: str
    expires_at: datetime


def decode_token(settings: Settings, token: str, *, expected_type: str) -> TokenClaims:
    """Return the verified claims, or raise `AuthError`.

    The token type is checked explicitly so a refresh token cannot be presented as
    an access token.

    **This does not consult the revocation list.** Signature, expiry and type are
    properties of the token; whether it has been taken back is a question for the
    database, and this module deliberately has no session. `token_service.assert_live`
    is the other half, and the two are called together in `deps.get_current_candidate`
    and in the refresh route.
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise AuthError(f"Invalid token: {exc}") from exc

    if payload.get("type") != expected_type:
        raise AuthError(f"Expected a {expected_type} token")

    try:
        subject = uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise AuthError("Token subject is missing or malformed") from exc

    jti = payload.get("jti")
    if not isinstance(jti, str) or not jti:
        # Every token this application has ever issued carries one. A token without
        # it is either forged or from a scheme that predates M1, and either way it
        # cannot be revoked — so it is refused rather than trusted unconditionally.
        raise AuthError("Token id is missing")

    try:
        expires_at = datetime.fromtimestamp(float(payload["exp"]), tz=UTC)
    except (KeyError, TypeError, ValueError) as exc:  # pragma: no cover - pyjwt enforces exp
        raise AuthError("Token expiry is missing or malformed") from exc

    return TokenClaims(
        subject=subject, jti=jti, token_type=str(payload["type"]), expires_at=expires_at
    )
