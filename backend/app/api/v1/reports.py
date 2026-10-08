"""Report builder and export endpoints (section 16)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Query, Response

from app.api.deps import ProjectContext, ProjectCtx, requires
from app.core.errors import Forbidden, NotFound
from app.core.policy import Permission
from app.models.collaboration import (ExportJob, ExportRequest, ReportDefinition,
                                      ReportDefinitionCreate, ReportPreview)
from app.repositories import export_jobs, report_definitions
from app.services import audit, exports, reports, storage
from app.workers import queue

router = APIRouter(tags=["reports"], prefix="/projects/{project_id}")

MEDIA_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "json": "application/json",
    "markdown": "text/markdown; charset=utf-8",
    "gherkin": "application/zip",
    "zip": "application/zip",
}


@router.get("/reports/datasets")
async def datasets(project_id: str, ctx: ProjectCtx) -> list[dict[str, Any]]:
    """The allowlisted datasets and the columns this caller may read."""
    ctx.require(Permission.REPORT_READ)
    out = []
    for template in reports.templates():
        allowed = reports.allowed_columns(template["dataset"],
                                          permissions=ctx.permissions,
                                          is_client=ctx.is_client)
        out.append({**template, "allowedColumns": [c.describe() for c in allowed]})
    return out


@router.post("/reports/preview", response_model=ReportPreview)
async def preview(project_id: str, body: dict[str, Any], ctx: ProjectCtx) -> ReportPreview:
    ctx.require(Permission.REPORT_READ)
    return await reports.build(ctx.project, body["dataset"],
                               filters=body.get("filters", {}),
                               fields=body.get("fields", []),
                               permissions=ctx.permissions, is_client=ctx.is_client,
                               limit=int(body.get("limit", 500)))


@router.get("/reports/definitions", response_model=list[ReportDefinition])
async def list_definitions(project_id: str, ctx: ProjectCtx) -> list[ReportDefinition]:
    ctx.require(Permission.REPORT_READ)
    return await report_definitions.list({
        "projectId": project_id,
        "$or": [{"ownerId": ctx.user.id}, {"sharedWithProject": True}],
    }, sort=[("createdAt", -1)])


@router.post("/reports/definitions", response_model=ReportDefinition, status_code=201)
async def save_definition(project_id: str, payload: ReportDefinitionCreate,
                          ctx: ProjectContext = requires(Permission.REPORT_MANAGE)
                          ) -> ReportDefinition:
    reports.validate_filters(payload.filters)
    allowed = {c.key for c in reports.allowed_columns(str(payload.dataset),
                                                      permissions=ctx.permissions,
                                                      is_client=ctx.is_client)}
    denied = set(payload.fields) - allowed
    if denied:
        raise Forbidden("A saved template cannot include fields you may not read",
                        details={"denied": sorted(denied)})
    definition = ReportDefinition(project_id=project_id, owner_id=ctx.user.id,
                                  **payload.model_dump(by_alias=False))
    await report_definitions.insert(definition)
    return definition


@router.get("/exports", response_model=list[ExportJob])
async def list_exports(project_id: str, ctx: ProjectCtx) -> list[ExportJob]:
    ctx.require(Permission.REPORT_READ)
    return await export_jobs.list({"projectId": project_id}, sort=[("createdAt", -1)],
                                  limit=50)


@router.post("/exports", status_code=202)
async def start_export(project_id: str, payload: ExportRequest,
                       idempotency_key: str | None = Header(None),
                       asynchronous: bool = Query(False, alias="async"),
                       ctx: ProjectContext = requires(Permission.EXPORT_RUN)
                       ) -> dict[str, Any]:
    """Start an export. Large exports run asynchronously with a job id."""
    reports.validate_filters(payload.filters)
    if asynchronous:
        job = await queue.enqueue(
            "export",
            {"projectId": project_id, "request": payload.model_dump(by_alias=True),
             "permissions": sorted(str(p) for p in ctx.permissions),
             "isClient": ctx.is_client},
            project_id=project_id,
            idempotency_key=payload.idempotency_key or idempotency_key,
            requested_by=ctx.user.id)
        return {"jobId": job.id, "status": str(job.status), "async": True}

    result = await exports.run_export(ctx.project, payload,
                                      permissions=ctx.permissions,
                                      is_client=ctx.is_client, actor_id=ctx.user.id)
    await audit.record("export.created", project_id=project_id, actor_id=ctx.user.id,
                       object_type="exportJob", object_id=result.id,
                       detail={"format": str(payload.format),
                               "rowCounts": result.row_counts})
    return {"exportJobId": result.id, "status": str(result.status),
            "filename": result.filename, "rowCounts": result.row_counts,
            "warnings": result.warnings, "schemaVersion": result.schema_version,
            "async": False}


@router.get("/exports/{export_id}/download")
async def download_export(project_id: str, export_id: str,
                          ctx: ProjectContext = requires(Permission.EXPORT_RUN)
                          ) -> Response:
    job = await export_jobs.get(export_id, projectId=project_id)
    if not job or not job.object_key:
        raise NotFound("Export not found")
    # The permissions applied when the file was produced still bind the download.
    if ctx.is_client and not job.parameters.get("clientSafe", False):
        raise Forbidden("This export was produced with internal fields")
    data = storage.get_bytes(job.object_key)
    await audit.record("export.downloaded", project_id=project_id, actor_id=ctx.user.id,
                       object_type="exportJob", object_id=export_id)
    media = MEDIA_TYPES.get(str(job.format), "application/octet-stream")
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition":
                             f'attachment; filename="{job.filename}"'})
