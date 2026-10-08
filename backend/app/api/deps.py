"""Request scoped authentication and project authorization context.

Authorization is resolved once per request and then enforced on every record,
chunk, search result, report row, download and job result (section 4).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Header, Path, Request

from app.core.errors import Forbidden, NotFound, Unauthorized
from app.core.policy import (APPROVER_ROLES, Permission, Role, is_client_role,
                             is_platform_admin, is_superuser, permissions_for)
from app.core.security import decode_token
from app.core.utils import as_utc, utcnow
from app.models.identity import ProjectMember, User
from app.models.project import Project
from app.repositories import members as members_repo
from app.repositories import projects as projects_repo
from app.repositories import users as users_repo


async def current_user(authorization: Annotated[str | None, Header()] = None) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Authentication required")
    payload = decode_token(authorization.split(" ", 1)[1].strip())
    user = await users_repo.get(payload.get("sub", ""))
    if not user or not user.active:
        raise Unauthorized("Account is not active")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


@dataclass
class ProjectContext:
    user: User
    project: Project
    member: ProjectMember | None
    permissions: set[Permission] = field(default_factory=set)
    roles: list[str] = field(default_factory=list)
    #: True when the caller reached this project through the platform owner
    #: standing rather than a membership record. Recorded in the audit trail.
    via_superuser: bool = False

    @property
    def is_client(self) -> bool:
        return self.user.is_client or is_client_role(self.roles)

    @property
    def is_superuser(self) -> bool:
        return is_superuser(self.roles)

    @property
    def is_approver(self) -> bool:
        return bool({Role(r) for r in self.roles if r in set(Role)} & APPROVER_ROLES)

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions

    def require(self, *permissions: Permission) -> None:
        missing = [p for p in permissions if p not in self.permissions]
        if missing:
            raise Forbidden(
                "You do not have permission to perform this action",
                details={"missing": [str(p) for p in missing]},
            )

    def require_any(self, *permissions: Permission) -> None:
        if not any(p in self.permissions for p in permissions):
            raise Forbidden(
                "You do not have permission to perform this action",
                details={"anyOf": [str(p) for p in permissions]},
            )


async def project_context(
    project_id: Annotated[str, Path()],
    user: CurrentUser,
    request: Request,
) -> ProjectContext:
    project = await projects_repo.get(project_id)
    if not project:
        # A non member must not be able to probe project existence.
        raise NotFound("Project not found")

    member = await members_repo.find_one({"projectId": project_id, "userId": user.id})
    roles = list(user.global_roles)
    owner = is_superuser(roles)
    if member:
        # The platform owner is not locked out by a stale membership record.
        if member.revoked_at is not None and not owner:
            raise Forbidden("Project access was revoked")
        if (member.expires_at is not None and as_utc(member.expires_at) < utcnow()
                and not owner):
            raise Forbidden("Project access has expired")
        roles += member.roles
    elif not is_platform_admin(user.global_roles):
        raise NotFound("Project not found")

    permissions = permissions_for(roles)
    request.state.project_id = project_id
    return ProjectContext(user=user, project=project, member=member,
                          permissions=permissions, roles=roles,
                          via_superuser=owner and member is None)


ProjectCtx = Annotated[ProjectContext, Depends(project_context)]


def requires(*permissions: Permission):
    """Dependency factory enforcing project scoped permissions."""

    async def _dep(ctx: ProjectCtx) -> ProjectContext:
        ctx.require(*permissions)
        return ctx

    return Depends(_dep)


def requires_any(*permissions: Permission):
    async def _dep(ctx: ProjectCtx) -> ProjectContext:
        ctx.require_any(*permissions)
        return ctx

    return Depends(_dep)


async def system_admin(user: CurrentUser) -> User:
    """Deployment administration: a system administrator or the platform owner."""
    if not is_platform_admin(user.global_roles):
        raise Forbidden("System administrator role required")
    return user


SystemAdmin = Annotated[User, Depends(system_admin)]
