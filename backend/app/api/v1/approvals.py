"""Approval, baseline and change request endpoints (section 10)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import ProjectContext, ProjectCtx, requires
from app.core.errors import Forbidden, NotFound
from app.core.policy import Permission
from app.models.approval import (ApprovalEvent, ApprovalManifest, ApprovalRevoke,
                                 ApprovalSubmit, Baseline, BaselineComparison,
                                 BaselineCreate, ChangeRequest,
                                 ChangeRequestCreate, ChangeRequestDecide)
from app.repositories import (approval_events, approval_manifests, backlog_items,
                              baselines, change_requests)
from app.services import approvals, baselines as baseline_service

router = APIRouter(tags=["approvals"], prefix="/projects/{project_id}")


@router.get("/approvals/inbox")
async def approval_inbox(project_id: str, ctx: ProjectCtx) -> dict[str, Any]:
    """Items waiting for a first approval or for renewed approval."""
    ctx.require(Permission.APPROVAL_PREVIEW)
    pending = await backlog_items.list({
        "projectId": project_id,
        "state": {"$nin": ["archived"]},
        "$or": [{"approvedVersion": None}, {"requiresReapproval": True}],
    }, sort=[("order", 1)], limit=1000)
    roots = [i for i in pending if i.type in ("epic", "feature")]
    return {
        "candidates": [{
            "itemId": i.id, "stableId": i.stable_id, "type": str(i.type),
            "title": i.title, "currentVersion": i.current_version,
            "approvedVersion": i.approved_version,
            "requiresReapproval": i.requires_reapproval,
            "stale": i.stale,
        } for i in roots] or [{
            "itemId": i.id, "stableId": i.stable_id, "type": str(i.type),
            "title": i.title, "currentVersion": i.current_version,
            "approvedVersion": i.approved_version,
            "requiresReapproval": i.requires_reapproval, "stale": i.stale,
        } for i in pending],
        "pendingCount": len(pending),
        "canDecide": ctx.has(Permission.APPROVAL_DECIDE),
        "canWaive": ctx.has(Permission.APPROVAL_WAIVE),
    }


@router.post("/approvals/preview/{root_id}", response_model=ApprovalManifest)
async def preview(project_id: str, root_id: str,
                  ctx: ProjectContext = requires(Permission.APPROVAL_PREVIEW)
                  ) -> ApprovalManifest:
    """Exact version manifest, counts, blockers, totals and diff (REQ-APP-02)."""
    return await approvals.build_manifest(ctx.project, root_id, actor_id=ctx.user.id,
                                          actor_is_approver=ctx.is_approver)


@router.get("/approvals/manifests/{manifest_id}", response_model=ApprovalManifest)
async def get_manifest(project_id: str, manifest_id: str,
                       ctx: ProjectContext = requires(Permission.APPROVAL_PREVIEW)
                       ) -> ApprovalManifest:
    manifest = await approval_manifests.get(manifest_id, projectId=project_id)
    if not manifest:
        raise NotFound("Manifest not found")
    return manifest


@router.post("/approvals/decisions", response_model=ApprovalEvent, status_code=201)
async def decide(project_id: str, payload: ApprovalSubmit,
                 ctx: ProjectContext = requires(Permission.APPROVAL_DECIDE)
                 ) -> ApprovalEvent:
    """Submit an approval decision for an exact manifest.

    The operation is atomic: if any included version changed since the preview,
    nothing is approved and the response carries a refreshed diff.
    """
    if not ctx.is_approver:
        raise Forbidden("Your role does not carry approval authority in this project")
    return await approvals.submit(ctx.project, payload, actor_id=ctx.user.id,
                                  actor_email=ctx.user.email,
                                  can_waive=ctx.has(Permission.APPROVAL_WAIVE))


@router.get("/approvals/events", response_model=list[ApprovalEvent])
async def list_events(project_id: str, ctx: ProjectCtx,
                      root_id: str | None = Query(None),
                      limit: int = Query(50, le=200)) -> list[ApprovalEvent]:
    ctx.require(Permission.APPROVAL_PREVIEW)
    query: dict[str, Any] = {"projectId": project_id}
    if root_id:
        query["rootId"] = root_id
    return await approval_events.list(query, sort=[("decidedAt", -1)], limit=limit)


@router.post("/approvals/events/{event_id}/revoke", response_model=ApprovalEvent)
async def revoke(project_id: str, event_id: str, payload: ApprovalRevoke,
                 ctx: ProjectContext = requires(Permission.APPROVAL_REVOKE)
                 ) -> ApprovalEvent:
    return await approvals.revoke(project_id, event_id, reason=payload.reason,
                                  item_ids=payload.item_ids, actor_id=ctx.user.id)


# --- baselines --------------------------------------------------------------

@router.get("/baselines", response_model=list[Baseline])
async def list_baselines(project_id: str, ctx: ProjectCtx) -> list[Baseline]:
    ctx.require(Permission.BACKLOG_READ)
    return await baselines.list({"projectId": project_id}, sort=[("createdAt", -1)])


@router.post("/baselines", response_model=Baseline, status_code=201)
async def create_baseline(project_id: str, payload: BaselineCreate,
                          ctx: ProjectContext = requires(Permission.BASELINE_MANAGE)
                          ) -> Baseline:
    return await baseline_service.create(ctx.project, payload, actor_id=ctx.user.id)


@router.get("/baselines/{baseline_id}/compare", response_model=BaselineComparison)
async def compare_baseline(project_id: str, baseline_id: str,
                           ctx: ProjectCtx) -> BaselineComparison:
    ctx.require(Permission.BACKLOG_READ)
    return await baseline_service.compare(ctx.project, baseline_id)


# --- change requests --------------------------------------------------------

@router.get("/change-requests", response_model=list[ChangeRequest])
async def list_change_requests(project_id: str, ctx: ProjectCtx) -> list[ChangeRequest]:
    ctx.require(Permission.BACKLOG_READ)
    return await change_requests.list({"projectId": project_id},
                                      sort=[("createdAt", -1)], limit=500)


@router.post("/change-requests", response_model=ChangeRequest, status_code=201)
async def create_change_request(project_id: str, payload: ChangeRequestCreate,
                                ctx: ProjectContext = requires(Permission.BACKLOG_EDIT)
                                ) -> ChangeRequest:
    return await baseline_service.create_change_request(ctx.project, payload,
                                                        actor_id=ctx.user.id)


@router.post("/change-requests/{request_id}/decide", response_model=ChangeRequest)
async def decide_change_request(project_id: str, request_id: str,
                                payload: ChangeRequestDecide,
                                ctx: ProjectContext = requires(Permission.CHANGE_DECIDE)
                                ) -> ChangeRequest:
    return await baseline_service.decide_change_request(project_id, request_id, payload,
                                                        actor_id=ctx.user.id)
