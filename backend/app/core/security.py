"""Password hashing and bearer token handling.

Company SSO through a configurable OIDC provider is the recommended production
path (section 4); local credentials exist so a company hosted deployment works
before the identity provider is wired in.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings
from app.core.errors import Unauthorized
from app.core.utils import utcnow

#: bcrypt only considers the first 72 bytes of a password, so the input is
#: truncated explicitly rather than failing on long passphrases.
_MAX_PASSWORD_BYTES = 72


def _encode(raw: str) -> bytes:
    return raw.encode("utf-8")[:_MAX_PASSWORD_BYTES]


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(_encode(raw), bcrypt.gensalt()).decode("ascii")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_encode(raw), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str, *, extra: dict[str, Any] | None = None,
                        minutes: int | None = None) -> str:
    expires = utcnow() + timedelta(minutes=minutes or settings.access_token_minutes)
    payload: dict[str, Any] = {"sub": subject, "exp": expires, "iat": utcnow()}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:  # pragma: no cover - defensive
        raise Unauthorized("Invalid or expired token") from exc
