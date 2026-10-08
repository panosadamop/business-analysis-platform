"""Client collaboration endpoints (section 15)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, ProjectContext, ProjectCtx, requires
from app.core.policy import Permission
from app.models.collaboration import (ClientAcceptance, Comment, CommentCreate,
                                      ShareGrant, ShareGrantCreate)
from app.repositories import share_grants
from app.services import sharing

router = APIRouter(tags=["sharing"], prefix="/projects/{project_id}")


@router.get("/shares", response_model=list[ShareGrant])
async def list_shares(project_id: str,
                      ctx: ProjectContext = requires(Permission.SHARE_MANAGE)
                      ) -> list[ShareGrant]:
    return await share_grants.list({"projectId": project_id}, sort=[("createdAt", -1)])


@router.post("/shares", response_model=ShareGrant, status_code=201)
async def create_share(project_id: str, payload: ShareGrantCreate,
                       ctx: ProjectContext = requires(Permission.SHARE_MANAGE)
                       ) -> ShareGrant:
    return await sharing.create_grant(project_id, payload, actor_id=ctx.user.id)


@router.post("/shares/{grant_id}/revoke", response_model=ShareGrant)
async def revoke_share(project_id: str, grant_id: str,
                       ctx: ProjectContext = requires(Permission.SHARE_MANAGE)
                       ) -> ShareGrant:
    return await sharing.revoke_grant(project_id, grant_id, actor_id=ctx.user.id)


@router.get("/comments", response_model=list[Comment])
async def list_comments(project_id: str, ctx: ProjectCtx,
                        target_id: str = Query(...)) -> list[Comment]:
    return await sharing.list_comments(project_id, target_id, is_client=ctx.is_client)


@router.post("/comments", response_model=Comment, status_code=201)
async def add_comment(project_id: str, payload: CommentCreate,
                      ctx: ProjectCtx) -> Comment:
    ctx.require_any(Permission.COMMENT_INTERNAL, Permission.CLIENT_COMMENT)
    return await sharing.add_comment(project_id, payload, author=ctx.user,
                                     is_client=ctx.is_client)


client = APIRouter(tags=["client"], prefix="/client")


@client.get("/projects")
async def my_shared_projects(user: CurrentUser) -> list[dict[str, Any]]:
    """Projects a client reviewer can see, resolved purely from share grants."""
    from app.repositories import projects as projects_repo

    grants = await sharing.active_grants_for(user)
    project_ids = sorted({g.project_id for g in grants})
    rows = await projects_repo.list({"_id": {"$in": project_ids}})
    by_id = {p.id: p for p in rows}
    return [{
        "projectId": project_id,
        "name": by_id[project_id].name if project_id in by_id else "Project",
        "clientName": by_id[project_id].client_name if project_id in by_id else None,
        "items": sum(len(g.versions) for g in grants if g.project_id == project_id),
        "allowAcceptance": any(g.allow_acceptance for g in grants
                               if g.project_id == project_id),
        "expiresAt": min((g.expires_at for g in grants
                          if g.project_id == project_id and g.expires_at),
                         default=None),
    } for project_id in project_ids if project_id in by_id]


@client.get("/projects/{project_id}/workspace")
async def workspace(project_id: str, user: CurrentUser) -> dict[str, Any]:
    return await sharing.client_workspace(user, project_id)


@client.post("/projects/{project_id}/acceptance")
async def acceptance(project_id: str, payload: ClientAcceptance,
                     user: CurrentUser) -> dict[str, Any]:
    """Client business acceptance, recorded separately from internal approval."""
    return await sharing.record_acceptance(user, project_id, payload)
