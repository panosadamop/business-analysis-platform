"""Authentication endpoints.

Local credentials exist so a company hosted deployment works before the OIDC
identity provider is configured. The OIDC settings endpoint tells the client
which provider to use when one is configured.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings
from app.core.errors import Unauthorized
from app.core.security import create_access_token, verify_password
from app.core.utils import utcnow
from app.api.deps import CurrentUser
from app.models.identity import LoginRequest, PublicUser, TokenResponse
from app.repositories import users
from app.services import audit

router = APIRouter(tags=["auth"])


def _public(user) -> PublicUser:
    return PublicUser(id=user.id, email=user.email, display_name=user.display_name,
                      global_roles=user.global_roles, is_client=user.is_client,
                      locale=user.locale, active=user.active)


@router.post("/auth/login", response_model=TokenResponse)
async def login(payload: LoginRequest) -> TokenResponse:
    user = await users.find_one({"email": payload.email.lower()})
    if not user or not user.password_hash or not verify_password(payload.password,
                                                                 user.password_hash):
        # The same message for unknown account and wrong password.
        raise Unauthorized("Email or password is incorrect")
    if not user.active:
        raise Unauthorized("This account is disabled")
    await users.update(user.id, {"lastLoginAt": utcnow()})
    await audit.record("auth.login", actor_id=user.id, actor_email=user.email)
    return TokenResponse(
        access_token=create_access_token(user.id, extra={"email": user.email}),
        expires_in=settings.access_token_minutes * 60,
        user=_public(user))


@router.get("/auth/me", response_model=PublicUser)
async def me(user: CurrentUser) -> PublicUser:
    return _public(user)


@router.get("/auth/providers")
async def providers() -> dict:
    return {
        "local": True,
        "oidc": bool(settings.oidc_issuer),
        "issuer": settings.oidc_issuer,
        "clientId": settings.oidc_client_id,
        "note": ("Company SSO through a configurable OIDC provider is the recommended "
                 "production path. Public anonymous sharing is disabled by default."),
    }
