"""Evidence ingestion models (section 6)."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.models.common import Base, Classification, Doc, Warning


class SourceKind(StrEnum):
    BRIEF = "brief"
    MEETING_NOTES = "meeting_notes"
    WORD = "word"
    EXCEL = "excel"
    CSV = "csv"
    JSON = "json"
    PDF = "pdf"
    RECORDING = "recording"
    FIGMA = "figma"
    ADOBE_XD = "adobe_xd"
    SCHEDULE = "schedule"
    IMAGE = "image"
    API_SPEC = "api_spec"
    OTHER = "other"


class ExtractionStatus(StrEnum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    READY = "ready"
    FAILED = "failed"
    EXCLUDED = "excluded"
    NEEDS_PASSWORD = "needs_password"
    UNSUPPORTED = "unsupported"


class Authority(StrEnum):
    """Analyst ranking used when evidence conflicts (section 6.2)."""

    CONTRACTUAL = "contractual"
    CONFIRMED = "confirmed"
    WORKING = "working"
    INDICATIVE = "indicative"


class SourceDocument(Doc):
    project_id: str
    title: str
    kind: SourceKind = SourceKind.OTHER
    classification: Classification = Classification.CONFIDENTIAL
    authority: Authority = Authority.WORKING
    current_version: int = 1
    current_version_id: str | None = None
    content_hash: str | None = None
    excluded: bool = False
    exclusion_reason: str | None = None
    tags: list[str] = Field(default_factory=list)
    uploaded_by: str | None = None


class SourceVersion(Doc):
    project_id: str
    document_id: str
    version: int = 1
    filename: str
    mime_type: str | None = None
    size_bytes: int = 0
    content_hash: str
    storage_key: str | None = None
    status: ExtractionStatus = ExtractionStatus.PENDING
    extractor: str | None = None
    extractor_version: str | None = None
    normalized_text: str | None = None
    #: Extraction metadata: sheet names, page count, duration, design nodes.
    meta: dict = Field(default_factory=dict)
    warnings: list[Warning] = Field(default_factory=list)
    failure_reason: str | None = None
    #: Spreadsheets: were values cached by the producing tool or recalculated here.
    values_recalculated: bool = False
    uploaded_by: str | None = None
    external_revision: str | None = None
    ignored_sections: list[str] = Field(default_factory=list)


class SourceChunk(Doc):
    project_id: str
    source_version_id: str
    document_id: str
    ordinal: int
    text: str
    locator_kind: str
    locator_value: str
    page: int | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    speaker: str | None = None
    classification: Classification = Classification.CONFIDENTIAL
    confidence: float | None = None
    low_confidence: bool = False
    embedding_ref: str | None = None
    token_estimate: int = 0


class TranscriptSegment(Doc):
    project_id: str
    source_version_id: str
    start_ms: int
    end_ms: int
    speaker: str | None = None
    #: Diarization labels never imply verified speaker identity.
    speaker_verified: bool = False
    text: str
    confidence: float = 1.0
    corrected: bool = False
    corrected_by: str | None = None
    corrected_at: datetime | None = None


class SourceCreate(Base):
    title: str
    kind: SourceKind = SourceKind.OTHER
    classification: Classification | None = None
    authority: Authority = Authority.WORKING
    tags: list[str] = Field(default_factory=list)
    external_revision: str | None = None


class SourceUpdate(Base):
    title: str | None = None
    kind: SourceKind | None = None
    classification: Classification | None = None
    authority: Authority | None = None
    excluded: bool | None = None
    exclusion_reason: str | None = None
    tags: list[str] | None = None
    ignored_sections: list[str] | None = None


class SegmentUpdate(Base):
    text: str | None = None
    speaker: str | None = None
    confidence: float | None = None


class SourceView(Base):
    """Permission aware projection. Restricted sources are indicated, not leaked."""

    id: str
    project_id: str
    title: str
    kind: str
    classification: str
    authority: str
    status: str
    current_version: int
    current_version_id: str | None = None
    excluded: bool = False
    size_bytes: int = 0
    filename: str | None = None
    warnings: list[Warning] = Field(default_factory=list)
    chunk_count: int = 0
    duration_ms: int | None = None
    created_at: datetime | None = None
    access_restricted: bool = False


class ImpactReport(Doc):
    """REQ-KNOW-08 / AT-15 — what a changed source touches."""

    project_id: str
    source_version_id: str
    previous_version_id: str | None = None
    generated_at: datetime
    affected: list[dict] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)
    acknowledged_by: str | None = None
