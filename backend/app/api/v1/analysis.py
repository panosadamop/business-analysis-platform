"""Analysis job endpoints (section 8)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Query

from app.api.deps import ProjectContext, ProjectCtx, requires
from app.core.errors import NotFound
from app.core.policy import Permission
from app.core.utils import utcnow
from app.models.analysis import (AnalysisJob, AnalysisRunRequest, ReviewFinding)
from app.repositories import analysis_jobs, findings
from app.services import audit
from app.workers import queue

router = APIRouter(tags=["analysis"], prefix="/projects/{project_id}")


@router.post("/analysis/runs", response_model=AnalysisJob, status_code=202)
async def start_run(project_id: str, payload: AnalysisRunRequest,
                    idempotency_key: str | None = Header(None),
                    ctx: ProjectContext = requires(Permission.ANALYSIS_RUN)
                    ) -> AnalysisJob:
    """Queue a BA to Technical Analyst to QA run on the current evidence."""
    from app.ai import orchestrator

    if idempotency_key and not payload.idempotency_key:
        payload.idempotency_key = idempotency_key
    job = await orchestrator.start_job(project_id, payload, actor_id=ctx.user.id)
    await queue.enqueue("analysis", {"analysisJobId": job.id}, project_id=project_id,
                        idempotency_key=f"analysis-{job.id}", requested_by=ctx.user.id)
    return job


@router.get("/analysis/runs", response_model=list[AnalysisJob])
async def list_runs(project_id: str, ctx: ProjectCtx,
                    limit: int = Query(20, le=100)) -> list[AnalysisJob]:
    ctx.require(Permission.ANALYSIS_READ)
    return await analysis_jobs.list({"projectId": project_id},
                                    sort=[("createdAt", -1)], limit=limit)


@router.get("/analysis/runs/{job_id}", response_model=AnalysisJob)
async def get_run(project_id: str, job_id: str, ctx: ProjectCtx) -> AnalysisJob:
    ctx.require(Permission.ANALYSIS_READ)
    job = await analysis_jobs.get(job_id, projectId=project_id)
    if not job:
        raise NotFound("Analysis job not found")
    return job


@router.post("/analysis/runs/{job_id}/cancel", response_model=AnalysisJob)
async def cancel_run(project_id: str, job_id: str,
                     ctx: ProjectContext = requires(Permission.ANALYSIS_RUN)
                     ) -> AnalysisJob:
    job = await analysis_jobs.get(job_id, projectId=project_id)
    if not job:
        raise NotFound("Analysis job not found")
    updated = await analysis_jobs.update(job_id, {"cancelRequested": True})
    await audit.record("analysis.cancel_requested", project_id=project_id,
                       actor_id=ctx.user.id, object_type="analysisJob", object_id=job_id)
    return updated


@router.post("/analysis/runs/{job_id}/resume", response_model=AnalysisJob)
async def resume_run(project_id: str, job_id: str,
                     ctx: ProjectContext = requires(Permission.ANALYSIS_RUN)
                     ) -> AnalysisJob:
    """Resume from the last validated stage; completed stages are not redone."""
    job = await analysis_jobs.get(job_id, projectId=project_id)
    if not job:
        raise NotFound("Analysis job not found")
    await analysis_jobs.update(job_id, {"cancelRequested": False, "status": "queued"})
    await queue.enqueue("analysis", {"analysisJobId": job_id}, project_id=project_id,
                        idempotency_key=f"analysis-resume-{job_id}-{utcnow():%Y%m%d%H%M%S}",
                        requested_by=ctx.user.id)
    return await analysis_jobs.require(job_id)


@router.get("/findings", response_model=list[ReviewFinding])
async def list_findings(project_id: str, ctx: ProjectCtx,
                        status: str | None = Query(None),
                        severity: str | None = Query(None),
                        target_id: str | None = Query(None),
                        role: str | None = Query(None)) -> list[ReviewFinding]:
    ctx.require(Permission.ANALYSIS_READ)
    query: dict[str, Any] = {"projectId": project_id}
    for field, value in (("status", status), ("severity", severity),
                         ("targetId", target_id), ("role", role)):
        if value:
            query[field] = value
    return await findings.list(query, sort=[("createdAt", -1)], limit=1000)


@router.post("/findings/{finding_id}/resolve", response_model=ReviewFinding)
async def resolve_finding(project_id: str, finding_id: str, body: dict[str, Any],
                          ctx: ProjectContext = requires(Permission.BACKLOG_EDIT)
                          ) -> ReviewFinding:
    """A specialist finding is resolved or waived by a human, never automatically."""
    finding = await findings.get(finding_id, projectId=project_id)
    if not finding:
        raise NotFound("Finding not found")
    status = body.get("status", "resolved")
    if status == "waived":
        ctx.require(Permission.APPROVAL_WAIVE)
    updated = await findings.update(finding_id, {
        "status": status, "resolvedBy": ctx.user.id, "resolvedAt": utcnow(),
        "waiverRationale": body.get("rationale")}, projectId=project_id)
    await audit.record("finding.resolved", project_id=project_id, actor_id=ctx.user.id,
                       object_type="reviewFinding", object_id=finding_id,
                       detail={"status": status, "rationale": body.get("rationale")})
    return updated


@router.get("/analysis/regenerate-preview/{item_id}")
async def regenerate_preview(project_id: str, item_id: str,
                             ctx: ProjectContext = requires(Permission.ANALYSIS_RUN)
                             ) -> dict[str, Any]:
    from app.ai import orchestrator

    return await orchestrator.regenerate_preview(project_id, item_id)
