"""Evidence lifecycle: upload, versioning, extraction and change impact."""
from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.core.errors import LimitExceeded, NotFound, ValidationFailed
from app.core.utils import new_id, sha256_bytes, utcnow
from app.models.common import Classification
from app.models.source import (ExtractionStatus, ImpactReport, SourceChunk,
                               SourceCreate, SourceDocument, SourceKind,
                               SourceVersion, SourceView, TranscriptSegment)
from app.repositories import (backlog_items, evidence_links, impact_reports,
                              source_chunks, source_documents, source_versions,
                              test_cases, transcript_segments)
from app.services import audit, extraction, storage

log = logging.getLogger(__name__)


def _limit_for(kind: SourceKind) -> int:
    return (settings.max_recording_bytes if kind == SourceKind.RECORDING
            else settings.max_document_bytes)


async def upload(project_id: str, *, filename: str, data: bytes, meta: SourceCreate,
                 actor_id: str, default_classification: Classification,
                 document_id: str | None = None) -> tuple[SourceDocument, SourceVersion]:
    """Store an original, extract it locally and index its chunks.

    A re-import of an existing document creates a new version. Evidence history
    is never overwritten (section 6.2).
    """
    kind = extraction.detect_kind(filename, meta.kind)
    limit = _limit_for(kind)
    if len(data) > limit:
        raise LimitExceeded(
            f"'{filename}' is {len(data)} bytes which exceeds the configured limit",
            details={"limitBytes": limit, "sizeBytes": len(data), "kind": str(kind)},
        )
    if not data:
        raise ValidationFailed("The uploaded file is empty")

    content_hash = sha256_bytes(data)
    classification = meta.classification or default_classification

    document: SourceDocument | None = None
    if document_id:
        document = await source_documents.get(document_id, projectId=project_id)
        if not document:
            raise NotFound("Source document not found")
    else:
        # Identical content already in the project is reported as a duplicate
        # rather than silently stored twice.
        document = await source_documents.find_one(
            {"projectId": project_id, "contentHash": content_hash})

    if document is None:
        document = SourceDocument(
            project_id=project_id, title=meta.title or filename, kind=kind,
            classification=classification, authority=meta.authority,
            tags=meta.tags, uploaded_by=actor_id, content_hash=content_hash,
        )
        await source_documents.insert(document)
        version_number = 1
    else:
        version_number = document.current_version + (
            0 if document.content_hash == content_hash and document_id is None else 1)
        version_number = max(version_number, 1)

    previous_version_id = document.current_version_id
    storage_key = f"projects/{project_id}/sources/{document.id}/v{version_number}/{filename}"
    storage.put_bytes(storage_key, data)

    version = SourceVersion(
        project_id=project_id, document_id=document.id, version=version_number,
        filename=filename, size_bytes=len(data), content_hash=content_hash,
        storage_key=storage_key, status=ExtractionStatus.EXTRACTING,
        uploaded_by=actor_id, external_revision=meta.external_revision,
    )
    await source_versions.insert(version)

    result = extraction.extract(data, filename, kind)
    version.status = result.status
    version.extractor = result.extractor
    version.extractor_version = extraction.EXTRACTOR_VERSION
    version.normalized_text = result.text[:2_000_000] if result.text else None
    version.meta = result.meta
    version.warnings = result.warnings
    version.failure_reason = result.failure_reason
    version.values_recalculated = result.values_recalculated
    await source_versions.replace(version)

    if result.chunks:
        await _store_chunks(project_id, document, version, result, classification)

    await source_documents.update(document.id, {
        "currentVersion": version_number,
        "currentVersionId": version.id,
        "contentHash": content_hash,
        "kind": str(kind),
        "classification": str(classification),
    })
    document.current_version = version_number
    document.current_version_id = version.id

    if previous_version_id and previous_version_id != version.id:
        await build_impact_report(project_id, version, previous_version_id)

    await audit.record("source.uploaded", project_id=project_id, actor_id=actor_id,
                       object_type="sourceVersion", object_id=version.id,
                       object_version=version_number,
                       detail={"filename": filename, "status": str(result.status),
                               "sizeBytes": len(data), "classification": str(classification)})
    return document, version


async def _store_chunks(project_id: str, document: SourceDocument, version: SourceVersion,
                        result: extraction.ExtractionResult,
                        classification: Classification) -> None:
    chunks = [
        SourceChunk(
            project_id=project_id, source_version_id=version.id, document_id=document.id,
            ordinal=index, text=chunk.text, locator_kind=chunk.locator_kind,
            locator_value=chunk.locator_value, page=chunk.page, start_ms=chunk.start_ms,
            end_ms=chunk.end_ms, speaker=chunk.speaker, classification=classification,
            confidence=chunk.confidence,
            low_confidence=bool(chunk.confidence is not None and chunk.confidence < 0.7),
            token_estimate=max(len(chunk.text) // 4, 1),
        )
        for index, chunk in enumerate(result.chunks)
    ]
    await source_chunks.insert_many(chunks)

    timestamped = [c for c in result.chunks if c.start_ms is not None]
    if timestamped:
        await transcript_segments.insert_many([
            TranscriptSegment(
                project_id=project_id, source_version_id=version.id,
                start_ms=c.start_ms or 0, end_ms=c.end_ms or (c.start_ms or 0) + 5000,
                speaker=c.speaker, text=c.text, confidence=c.confidence or 1.0,
            )
            for c in timestamped
        ])


async def build_impact_report(project_id: str, version: SourceVersion,
                              previous_version_id: str) -> ImpactReport:
    """REQ-KNOW-08 / AT-15 — mark everything a changed source touches as stale."""
    links = await evidence_links.list({"projectId": project_id,
                                       "sourceVersionId": previous_version_id})
    affected: list[dict[str, Any]] = []
    item_ids: list[str] = []
    test_ids: list[str] = []
    for link in links:
        affected.append({
            "targetType": link.target_type,
            "targetId": link.target_id,
            "targetVersion": link.target_version,
            "linkType": link.link_type,
            "reason": "The evidence this item derives from changed",
        })
        if link.target_type == "backlog_item":
            item_ids.append(link.target_id)
        elif link.target_type == "test_case":
            test_ids.append(link.target_id)

    # Approved history stays available; only current artifacts are marked stale.
    if item_ids:
        await backlog_items.raw_update({"_id": {"$in": item_ids}},
                                       {"$set": {"stale": True, "updatedAt": utcnow()}})
    if test_ids:
        await test_cases.raw_update({"_id": {"$in": test_ids}},
                                    {"$set": {"stale": True, "updatedAt": utcnow()}})

    report = ImpactReport(
        project_id=project_id, source_version_id=version.id,
        previous_version_id=previous_version_id, generated_at=utcnow(),
        affected=affected,
        summary={"items": len(set(item_ids)), "tests": len(set(test_ids)),
                 "total": len(affected)},
    )
    await impact_reports.insert(report)
    return report


async def view(document: SourceDocument, *, allowed: bool,
               version: SourceVersion | None = None) -> SourceView:
    """Project a document for a caller. Restricted sources are indicated only."""
    if not allowed:
        return SourceView(
            id=document.id, project_id=document.project_id, title="Restricted source",
            kind=str(document.kind), classification=str(document.classification),
            authority=str(document.authority), status="restricted",
            current_version=document.current_version, access_restricted=True,
        )
    chunk_count = await source_chunks.count({"sourceVersionId": version.id}) if version else 0
    return SourceView(
        id=document.id, project_id=document.project_id, title=document.title,
        kind=str(document.kind), classification=str(document.classification),
        authority=str(document.authority),
        status=str(version.status) if version else "pending",
        current_version=document.current_version,
        current_version_id=document.current_version_id,
        excluded=document.excluded,
        size_bytes=version.size_bytes if version else 0,
        filename=version.filename if version else None,
        warnings=version.warnings if version else [],
        chunk_count=chunk_count,
        duration_ms=(version.meta or {}).get("durationMs") if version else None,
        created_at=document.created_at,
    )


async def attach_transcript(project_id: str, version_id: str, text: str,
                            actor_id: str) -> int:
    """Attach a locally produced transcript to a recording version."""
    version = await source_versions.get(version_id, projectId=project_id)
    if not version:
        raise NotFound("Source version not found")
    chunks = extraction.parse_transcript_text(text)
    if not chunks:
        raise ValidationFailed(
            "No timestamped lines were found. Expected lines like '[01:23] Speaker: text'.")
    await source_chunks.delete_many({"sourceVersionId": version_id})
    await transcript_segments.delete_many({"sourceVersionId": version_id})
    document = await source_documents.require(version.document_id, projectId=project_id)
    await _store_chunks(project_id, document, version,
                        extraction.ExtractionResult(status=ExtractionStatus.READY,
                                                    text=text, chunks=chunks),
                        document.classification)
    await source_versions.update(version_id, {
        "status": str(ExtractionStatus.READY),
        "normalizedText": text[:2_000_000],
        "extractor": "local-transcription",
    })
    await audit.record("source.transcript_attached", project_id=project_id, actor_id=actor_id,
                       object_type="sourceVersion", object_id=version_id,
                       detail={"segments": len(chunks)})
    return len(chunks)


async def correct_segment(project_id: str, segment_id: str, *, text: str | None,
                          speaker: str | None, actor_id: str) -> TranscriptSegment:
    segment = await transcript_segments.get(segment_id, projectId=project_id)
    if not segment:
        raise NotFound("Transcript segment not found")
    changes: dict[str, Any] = {"corrected": True, "correctedBy": actor_id,
                               "correctedAt": utcnow()}
    if text is not None:
        changes["text"] = text
        changes["confidence"] = 1.0
    if speaker is not None:
        changes["speaker"] = speaker
    updated = await transcript_segments.update(segment_id, changes)
    if text is not None:
        await source_chunks.raw_update(
            {"sourceVersionId": segment.source_version_id, "startMs": segment.start_ms},
            {"$set": {"text": text, "lowConfidence": False}},
        )
    await audit.record("source.segment_corrected", project_id=project_id, actor_id=actor_id,
                       object_type="transcriptSegment", object_id=segment_id)
    return updated


async def chunk_ids_for_context(project_id: str, *,
                                include_excluded: bool = False) -> list[SourceChunk]:
    """Chunks eligible as AI context: current versions of included documents."""
    documents = await source_documents.list({"projectId": project_id})
    version_ids = [d.current_version_id for d in documents
                   if d.current_version_id and (include_excluded or not d.excluded)]
    if not version_ids:
        return []
    return await source_chunks.list({"projectId": project_id,
                                     "sourceVersionId": {"$in": version_ids}},
                                    sort=[("ordinal", 1)])


async def generate_storage_key(project_id: str, suffix: str) -> str:
    return f"projects/{project_id}/generated/{new_id()}/{suffix}"
