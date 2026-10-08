"""Sequential analyst workflow, findings and generated specifications
(sections 8 and 9.2)."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.models.common import (AnalystRole, ArtifactState, Base, Citation, Doc,
                               JobStatus, Money, Severity)


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class ModelUsage(Base):
    role: str
    model_id: str
    model_config_hash: str | None = None
    prompt_template_version: str | None = None
    deployment: str = "local"  # local | cloud
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: Money | None = None
    latency_ms: int = 0


class AnalysisStage(Base):
    role: AnalystRole
    status: StageStatus = StageStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    #: Checkpoint used to resume after failure (section 8.2).
    checkpoint: dict | None = None
    input_manifest: dict = Field(default_factory=dict)
    output_summary: dict = Field(default_factory=dict)
    usage: ModelUsage | None = None
    error: str | None = None
    cycle: int = 0


class AnalysisJob(Doc):
    project_id: str
    scope: dict = Field(default_factory=dict)  # item ids, source ids, regenerate flags
    status: JobStatus = JobStatus.QUEUED
    stages: list[AnalysisStage] = Field(default_factory=list)
    requested_by: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cycles_used: int = 0
    max_cycles: int = 3
    cancel_requested: bool = False
    progress: float = 0.0
    message: str | None = None
    warnings: list[dict] = Field(default_factory=list)
    created_counts: dict[str, int] = Field(default_factory=dict)
    total_cost: Money | None = None
    idempotency_key: str | None = None


class FindingStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    WAIVED = "waived"
    ESCALATED = "escalated"


class ReviewFinding(Doc):
    project_id: str
    job_id: str | None = None
    role: AnalystRole
    severity: Severity = Severity.MAJOR
    category: str = "quality"
    title: str
    rationale: str
    recommendation: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    target_version: int | None = None
    citations: list[Citation] = Field(default_factory=list)
    status: FindingStatus = FindingStatus.OPEN
    #: A specialist review is never human approval (section 8.1).
    blocking: bool = False
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    waiver_rationale: str | None = None
    cycle: int = 0


class SpecificationKind(StrEnum):
    FUNCTIONAL = "functional"
    NON_FUNCTIONAL = "non_functional"
    PROCESS_DIAGRAM = "process_diagram"
    DATA_MODEL = "data_model"
    API = "api"
    UX = "ux"
    DATA = "data"


class Specification(Doc):
    project_id: str
    item_id: str | None = None
    kind: SpecificationKind
    version: int = 1
    state: ArtifactState = ArtifactState.DRAFT
    title: str
    #: Markdown body for narrative specs.
    body: str | None = None
    #: Mermaid source for process diagrams.
    diagram_source: str | None = None
    #: Entities for data models, OpenAPI document for API specs.
    structured: dict = Field(default_factory=dict)
    requirement_ids: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    generated_by_role: str | None = None
    model_id: str | None = None
    validation: dict = Field(default_factory=dict)
    author_id: str | None = None
    change_note: str | None = None


class SpecificationCreate(Base):
    """An analyst writing a specification by hand rather than generating one."""

    kind: SpecificationKind
    title: str
    body: str | None = None
    diagram_source: str | None = None
    structured: dict = Field(default_factory=dict)
    item_id: str | None = None
    requirement_ids: list[str] = Field(default_factory=list)


class AnalysisRunRequest(Base):
    #: Empty means the whole project.
    item_ids: list[str] = Field(default_factory=list)
    source_version_ids: list[str] = Field(default_factory=list)
    roles: list[AnalystRole] = Field(default_factory=lambda: [AnalystRole.BA,
                                                             AnalystRole.TA,
                                                             AnalystRole.QA])
    regenerate: bool = False
    #: Explicit merge preview required before overwriting human edits.
    merge_preview: bool = True
    generate_specifications: bool = True
    generate_tests: bool = True
    max_cycles: int | None = None
    idempotency_key: str | None = None


class JobView(Base):
    id: str
    project_id: str
    status: str
    progress: float
    stages: list[AnalysisStage]
    message: str | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None
    created_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[dict] = Field(default_factory=list)
