"""Users, project membership and authentication payloads (section 4)."""
from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.models.common import Base, Doc, Email, Language


class User(Doc):
    email: Email
    display_name: str
    password_hash: str | None = None
    #: Platform wide roles. Project scoped roles live on ProjectMember.
    global_roles: list[str] = Field(default_factory=list)
    is_client: bool = False
    client_org: str | None = None
    locale: Language = Language.EN
    active: bool = True
    oidc_subject: str | None = None
    last_login_at: datetime | None = None


class PublicUser(Base):
    id: str
    email: str
    display_name: str
    global_roles: list[str] = Field(default_factory=list)
    is_client: bool = False
    locale: Language = Language.EN
    active: bool = True


class ProjectMember(Doc):
    project_id: str
    user_id: str
    roles: list[str] = Field(default_factory=list)
    #: Delivery role used for capacity and rate resolution.
    delivery_role: str | None = None
    allocation_percent: float = 100.0
    #: Client reviewers may be granted acceptance authority per project.
    acceptance_authority: bool = False
    invited_by: str | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None


class MemberView(Base):
    id: str
    user_id: str
    email: str
    display_name: str
    roles: list[str]
    delivery_role: str | None = None
    allocation_percent: float = 100.0
    acceptance_authority: bool = False
    expires_at: datetime | None = None
    revoked_at: datetime | None = None


class LoginRequest(Base):
    email: Email
    password: str


class TokenResponse(Base):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: PublicUser


class MemberCreate(Base):
    email: Email
    display_name: str | None = None
    roles: list[str]
    delivery_role: str | None = None
    allocation_percent: float = 100.0
    acceptance_authority: bool = False
    expires_at: datetime | None = None


class MemberUpdate(Base):
    roles: list[str] | None = None
    delivery_role: str | None = None
    allocation_percent: float | None = None
    acceptance_authority: bool | None = None
    expires_at: datetime | None = None
    revoked: bool | None = None
