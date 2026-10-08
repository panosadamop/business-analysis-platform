"""Client collaboration, comments, reports, exports and audit
(sections 15, 16 and 18)."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.models.common import Base, Doc, Email, JobStatus


class ShareGrant(Doc):
    """Section 15 — a client only ever sees explicitly granted versions."""

    project_id: str
    audience_user_id: str | None = None
    audience_email: Email | None = None
    label: str | None = None
    #: (itemId, version) pairs. Immutable approved versions by default.
    versions: list[dict] = Field(default_factory=list)
    include_drafts: bool = False
    include_questions: bool = True
    include_progress_report: bool = False
    include_tests: bool = False
    include_sources: bool = False
    allow_download: bool = False
    allow_acceptance: bool = False
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    revoked_by: str | None = None
    created_by: str | None = None
    access_log: list[dict] = Field(default_factory=list)


class ShareGrantCreate(Base):
    audience_email: Email
    label: str | None = None
    item_ids: list[str] = Field(default_factory=list)
    include_drafts: bool = False
    include_questions: bool = True
    include_progress_report: bool = False
    include_tests: bool = False
    include_sources: bool = False
    allow_download: bool = False
    allow_acceptance: bool = False
    expires_at: datetime | None = None


class CommentVisibility(StrEnum):
    INTERNAL = "internal"
    CLIENT = "client"


class Comment(Doc):
    project_id: str
    target_type: str
    target_id: str
    target_version: int | None = None
    body: str
    author_id: str
    visibility: CommentVisibility = CommentVisibility.INTERNAL
    requested_change: bool = False
    resolved: bool = False
    resolved_by: str | None = None
    parent_id: str | None = None


class CommentCreate(Base):
    target_type: str
    target_id: str
    target_version: int | None = None
    body: str
    visibility: CommentVisibility = CommentVisibility.INTERNAL
    requested_change: bool = False
    parent_id: str | None = None


class ClientAcceptance(Base):
    item_ids: list[str] = Field(default_factory=list)
    accepted: bool = True
    note: str | None = None


class ReportDataset(StrEnum):
    BACKLOG = "backlog"
    ESTIMATES_BY_ROLE = "estimates_by_role"
    PLANNED_VS_ACTUAL = "planned_vs_actual"
    COST_FORECAST = "cost_forecast"
    CAPACITY = "capacity"
    SPRINT_PROGRESS = "sprint_progress"
    KANBAN_FLOW = "kanban_flow"
    TRACEABILITY = "traceability"
    TESTBOOK = "testbook"
    APPROVAL_HISTORY = "approval_history"
    CHANGE_IMPACT = "change_impact"
    CONNECTOR_HEALTH = "connector_health"
    QUESTIONS = "questions"


class ReportDefinition(Doc):
    project_id: str
    name: str
    dataset: ReportDataset
    #: Validated allowlist only. No arbitrary database commands (REQ-REPORT-03).
    fields: list[str] = Field(default_factory=list)
    filters: dict = Field(default_factory=dict)
    group_by: list[str] = Field(default_factory=list)
    sort: list[dict] = Field(default_factory=list)
    aggregations: list[dict] = Field(default_factory=list)
    date_from: datetime | None = None
    date_to: datetime | None = None
    baseline_id: str | None = None
    chart_type: str | None = None
    owner_id: str | None = None
    shared_with_project: bool = False
    client_safe: bool = False


class ReportDefinitionCreate(Base):
    name: str
    dataset: ReportDataset
    fields: list[str] = Field(default_factory=list)
    filters: dict = Field(default_factory=dict)
    group_by: list[str] = Field(default_factory=list)
    sort: list[dict] = Field(default_factory=list)
    aggregations: list[dict] = Field(default_factory=list)
    baseline_id: str | None = None
    chart_type: str | None = None
    shared_with_project: bool = False


class ReportPreview(Base):
    dataset: str
    columns: list[dict] = Field(default_factory=list)
    rows: list[dict] = Field(default_factory=list)
    total_rows: int = 0
    truncated: bool = False
    snapshot_id: str
    generated_at: datetime
    applied_permissions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    totals: dict = Field(default_factory=dict)


class ExportFormat(StrEnum):
    XLSX = "xlsx"
    XLS = "xls"
    JSON = "json"
    MARKDOWN = "markdown"
    GHERKIN = "gherkin"
    ZIP = "zip"


class ExportJob(Doc):
    project_id: str
    definition_id: str | None = None
    dataset: str | None = None
    format: ExportFormat
    status: JobStatus = JobStatus.QUEUED
    requested_by: str | None = None
    parameters: dict = Field(default_factory=dict)
    snapshot_id: str | None = None
    object_key: str | None = None
    filename: str | None = None
    size_bytes: int = 0
    row_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    schema_version: str = "1.0"
    applied_permissions: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    error: str | None = None


class ExportRequest(Base):
    definition_id: str | None = None
    dataset: ReportDataset | None = None
    format: ExportFormat = ExportFormat.XLSX
    filters: dict = Field(default_factory=dict)
    fields: list[str] = Field(default_factory=list)
    baseline_id: str | None = None
    item_ids: list[str] = Field(default_factory=list)
    idempotency_key: str | None = None


class AuditEvent(Doc):
    project_id: str | None = None
    actor_id: str | None = None
    actor_email: str | None = None
    action: str
    object_type: str | None = None
    object_id: str | None = None
    object_version: int | None = None
    at: datetime
    detail: dict = Field(default_factory=dict)
    ip: str | None = None
    correlation_id: str | None = None


class EgressManifest(Doc):
    """Internal audit record of what left company infrastructure (section 8.3)."""

    project_id: str
    at: datetime
    allowed: bool
    provider: str | None = None
    model_id: str | None = None
    role: str | None = None
    classification: str | None = None
    #: Categories only. Sensitive payloads never enter ordinary logs.
    disclosure_categories: list[str] = Field(default_factory=list)
    redactions: dict[str, int] = Field(default_factory=dict)
    chunk_count: int = 0
    char_count: int = 0
    payload_hash: str | None = None
    blocked_reason: str | None = None
    actor_id: str | None = None


class JobRecord(Doc):
    """Durable queue entry for long running work (NFR-05)."""

    project_id: str | None = None
    kind: str
    payload: dict = Field(default_factory=dict)
    status: JobStatus = JobStatus.QUEUED
    attempts: int = 0
    max_attempts: int = 3
    available_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: float = 0.0
    message: str | None = None
    result: dict = Field(default_factory=dict)
    error: str | None = None
    cancel_requested: bool = False
    idempotency_key: str | None = None
    requested_by: str | None = None
    correlation_id: str | None = None
