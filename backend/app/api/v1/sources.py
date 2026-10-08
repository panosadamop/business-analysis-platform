"""Evidence workspace endpoints (section 6)."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, File, Form, Query, Response, UploadFile

from app.api.deps import ProjectContext, ProjectCtx, requires
from app.core.config import settings
from app.core.errors import Forbidden, NotFound
from app.core.policy import Permission
from app.models.common import Classification
from app.models.source import (SegmentUpdate, SourceCreate, SourceUpdate,
                               SourceView, TranscriptSegment)
from app.repositories import (impact_reports, source_chunks, source_documents,
                              source_versions, transcript_segments)
from app.services import audit, sources, storage

router = APIRouter(tags=["sources"], prefix="/projects/{project_id}")


def _may_read_raw(ctx: ProjectContext, classification: str) -> bool:
    if ctx.is_client:
        return False
    if classification == str(Classification.RESTRICTED):
        return ctx.has(Permission.SOURCE_RAW_READ)
    return ctx.has(Permission.SOURCE_READ)


@router.get("/sources", response_model=list[SourceView])
async def list_sources(ctx: ProjectCtx) -> list[SourceView]:
    ctx.require(Permission.SOURCE_READ)
    documents = await source_documents.list({"projectId": ctx.project.id},
                                            sort=[("createdAt", -1)])
    versions = {v.id: v for v in await source_versions.list(
        {"_id": {"$in": [d.current_version_id for d in documents
                         if d.current_version_id]}})}
    out: list[SourceView] = []
    for document in documents:
        allowed = _may_read_raw(ctx, str(document.classification))
        out.append(await sources.view(document, allowed=allowed,
                                      version=versions.get(document.current_version_id or "")))
    return out


@router.get("/sources/limits")
async def upload_limits(ctx: ProjectCtx) -> dict[str, Any]:
    """Limits are shown before upload, never discovered by a failed upload."""
    return {
        "maxDocumentBytes": settings.max_document_bytes,
        "maxRecordingBytes": settings.max_recording_bytes,
        "supported": {
            "documents": [".txt", ".md", ".docx", ".pdf", ".xlsx", ".xls", ".csv",
                          ".json", ".yaml"],
            "recordings": [".mp3", ".wav", ".m4a", ".mp4", ".mov", ".mkv"],
            "designs": ["Figma export", "Adobe XD export", ".png", ".jpg"],
        },
        "notes": [
            "Legacy .doc needs the isolated conversion worker.",
            "Images and scanned PDFs need the local OCR worker; without it the file is "
            "stored but not treated as analysed.",
            "Macros, scripts and external links are never executed during parsing.",
        ],
    }


@router.post("/sources", response_model=SourceView, status_code=201)
async def upload_source(project_id: str, file: UploadFile = File(...),
                        meta: str = Form("{}"),
                        document_id: str | None = Form(None),
                        ctx: ProjectContext = requires(Permission.SOURCE_UPLOAD)
                        ) -> SourceView:
    payload = SourceCreate(**(json.loads(meta) if meta else {}))
    if not payload.title:
        payload.title = file.filename or "Untitled source"
    data = await file.read()
    document, version = await sources.upload(
        project_id, filename=file.filename or "upload.bin", data=data, meta=payload,
        actor_id=ctx.user.id,
        default_classification=ctx.project.default_classification,
        document_id=document_id)
    return await sources.view(document, allowed=True, version=version)


@router.patch("/sources/{document_id}", response_model=SourceView)
async def update_source(project_id: str, document_id: str, payload: SourceUpdate,
                        ctx: ProjectContext = requires(Permission.SOURCE_MANAGE)
                        ) -> SourceView:
    document = await source_documents.get(document_id, projectId=project_id)
    if not document:
        raise NotFound("Source not found")
    changes = payload.model_dump(exclude_unset=True, by_alias=True, exclude_none=True)
    ignored = changes.pop("ignoredSections", None)
    updated = await source_documents.update(document_id, changes, projectId=project_id)
    if ignored is not None and document.current_version_id:
        await source_versions.update(document.current_version_id,
                                     {"ignoredSections": ignored})
    await audit.record("source.updated", project_id=project_id, actor_id=ctx.user.id,
                       object_type="sourceDocument", object_id=document_id,
                       detail={"fields": sorted(changes)})
    version = await source_versions.get(updated.current_version_id or "")
    return await sources.view(updated, allowed=True, version=version)


@router.get("/sources/{document_id}/versions")
async def list_versions(project_id: str, document_id: str,
                        ctx: ProjectCtx) -> list[dict[str, Any]]:
    ctx.require(Permission.SOURCE_READ)
    rows = await source_versions.list({"projectId": project_id,
                                       "documentId": document_id},
                                      sort=[("version", -1)])
    return [{"id": v.id, "version": v.version, "filename": v.filename,
             "status": str(v.status), "sizeBytes": v.size_bytes,
             "contentHash": v.content_hash, "uploadedBy": v.uploaded_by,
             "createdAt": v.created_at, "warnings": [w.model_dump(by_alias=True)
                                                     for w in v.warnings],
             "failureReason": v.failure_reason,
             "valuesRecalculated": v.values_recalculated,
             "extractor": v.extractor, "extractorVersion": v.extractor_version,
             "meta": v.meta}
            for v in rows]


@router.get("/sources/{document_id}/content")
async def source_content(project_id: str, document_id: str, ctx: ProjectCtx,
                         version_id: str | None = Query(None),
                         offset: int = Query(0), limit: int = Query(200)
                         ) -> dict[str, Any]:
    """Source viewer. Unauthorized callers get a restriction notice, not text."""
    document = await source_documents.get(document_id, projectId=project_id)
    if not document:
        raise NotFound("Source not found")
    if not _may_read_raw(ctx, str(document.classification)):
        return {"accessRestricted": True,
                "message": "You are not permitted to read this source.",
                "classification": str(document.classification)}
    target = version_id or document.current_version_id
    chunks = await source_chunks.list({"projectId": project_id,
                                       "sourceVersionId": target},
                                      sort=[("ordinal", 1)], limit=limit, offset=offset)
    total = await source_chunks.count({"projectId": project_id,
                                       "sourceVersionId": target})
    return {
        "accessRestricted": False,
        "documentId": document_id,
        "versionId": target,
        "total": total,
        "chunks": [{"id": c.id, "ordinal": c.ordinal, "text": c.text,
                    "locatorKind": c.locator_kind, "locatorValue": c.locator_value,
                    "page": c.page, "startMs": c.start_ms, "speaker": c.speaker,
                    "lowConfidence": c.low_confidence}
                   for c in chunks],
    }


@router.get("/sources/{document_id}/download")
async def download_source(project_id: str, document_id: str, ctx: ProjectCtx,
                          version_id: str | None = Query(None)) -> Response:
    document = await source_documents.get(document_id, projectId=project_id)
    if not document:
        raise NotFound("Source not found")
    if not _may_read_raw(ctx, str(document.classification)):
        raise Forbidden("You are not permitted to download this source")
    version = await source_versions.require(version_id or document.current_version_id or "")
    data = storage.get_bytes(version.storage_key or "")
    await audit.record("source.downloaded", project_id=project_id, actor_id=ctx.user.id,
                       object_type="sourceVersion", object_id=version.id)
    return Response(content=data, media_type=version.mime_type or "application/octet-stream",
                    headers={"Content-Disposition":
                             f'attachment; filename="{version.filename}"'})


@router.get("/sources/{document_id}/transcript", response_model=list[TranscriptSegment])
async def transcript(project_id: str, document_id: str, ctx: ProjectCtx,
                     version_id: str | None = Query(None)) -> list[TranscriptSegment]:
    document = await source_documents.get(document_id, projectId=project_id)
    if not document:
        raise NotFound("Source not found")
    if not _may_read_raw(ctx, str(document.classification)):
        raise Forbidden("You are not permitted to read this transcript")
    return await transcript_segments.list(
        {"projectId": project_id,
         "sourceVersionId": version_id or document.current_version_id},
        sort=[("startMs", 1)], limit=5000)


@router.post("/sources/versions/{version_id}/transcript")
async def attach_transcript(project_id: str, version_id: str, body: dict[str, str],
                            ctx: ProjectContext = requires(Permission.SOURCE_MANAGE)
                            ) -> dict[str, Any]:
    count = await sources.attach_transcript(project_id, version_id, body.get("text", ""),
                                            ctx.user.id)
    return {"segments": count,
            "note": "Speaker labels are suggestions and do not imply verified identity."}


@router.patch("/sources/segments/{segment_id}", response_model=TranscriptSegment)
async def correct_segment(project_id: str, segment_id: str, payload: SegmentUpdate,
                          ctx: ProjectContext = requires(Permission.SOURCE_UPLOAD)
                          ) -> TranscriptSegment:
    return await sources.correct_segment(project_id, segment_id, text=payload.text,
                                         speaker=payload.speaker, actor_id=ctx.user.id)


@router.get("/sources/impact")
async def impact(project_id: str, ctx: ProjectCtx) -> list[dict[str, Any]]:
    """Change impact reports produced when evidence changed (REQ-KNOW-08)."""
    ctx.require(Permission.SOURCE_READ)
    rows = await impact_reports.list({"projectId": project_id},
                                     sort=[("generatedAt", -1)], limit=50)
    return [r.model_dump(by_alias=True) for r in rows]
