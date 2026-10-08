"""Backlog hierarchy, artifact versions and estimates (sections 9 and 11)."""
from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import Field

from app.models.common import (ArtifactState, Base, Citation, Doc,
                               ExecutionStatus, ItemType, Money, Priority,
                               Provenance)


class AcceptanceCriterion(Base):
    id: str
    text: str
    #: Epic and feature criteria express outcome level acceptance.
    outcome_level: bool = False
    provenance: Provenance = Provenance.EVIDENCE
    citations: list[Citation] = Field(default_factory=list)
    verified_by_test_ids: list[str] = Field(default_factory=list)


class EstimateMethod(StrEnum):
    TEMPLATE = "template"
    AI_PROPOSED = "ai_proposed"
    EXPERT = "expert"
    PLANNING_POKER = "planning_poker"
    ANALOGY = "analogy"
    CALIBRATED = "calibrated"
    SPIKE_REQUIRED = "spike_required"


class RoleEffort(Base):
    role: str
    hours: float = 0.0
    low: float | None = None
    high: float | None = None


class Estimate(Doc):
    """Section 11.1. Zero never represents a missing estimate."""

    project_id: str
    item_id: str
    item_version: int | None = None
    method: EstimateMethod = EstimateMethod.TEMPLATE
    estimator_id: str | None = None
    estimated_at: datetime | None = None
    #: Independent of effort on purpose; no universal point to hour conversion.
    story_points: float | None = None
    role_efforts: list[RoleEffort] = Field(default_factory=list)
    overhead_hours: float = 0.0
    low_hours: float | None = None
    likely_hours: float | None = None
    high_hours: float | None = None
    confidence_label: str = "indicative"
    assumptions: list[str] = Field(default_factory=list)
    source_versions: list[str] = Field(default_factory=list)
    unknown: bool = False
    spike_required: bool = False
    note: str | None = None
    #: Rough parent estimate kept for comparison, never added to child rollups.
    is_rough_parent: bool = False
    superseded: bool = False


class EstimateRollup(Base):
    item_id: str
    unit: str = "person_hours"
    hours_per_person_day: float = 8.0
    own_hours: float = 0.0
    own_overhead_hours: float = 0.0
    children_hours: float = 0.0
    detailed_hours: float = 0.0
    rough_parent_hours: float | None = None
    low_hours: float = 0.0
    high_hours: float = 0.0
    person_days: float = 0.0
    story_points: float | None = None
    story_points_comparable: bool = True
    estimated_cost: Money | None = None
    role_breakdown: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    children_estimated: int = 0
    children_total: int = 0


class BacklogItem(Doc):
    project_id: str
    stable_id: str
    type: ItemType
    parent_id: str | None = None
    #: Materialised ancestor path, root first. Keeps subtree reads cheap.
    path: list[str] = Field(default_factory=list)
    order: float = 0.0
    title: str
    current_version: int = 1
    current_version_id: str | None = None
    state: ArtifactState = ArtifactState.DRAFT
    execution_status: ExecutionStatus = ExecutionStatus.NOT_STARTED
    approved_version: int | None = None
    approved_at: datetime | None = None
    #: REQ-APP-06 — a child change marks the parent bundle as needing renewal.
    requires_reapproval: bool = False
    stale: bool = False
    owner_id: str | None = None
    priority: Priority = Priority.MEDIUM
    labels: list[str] = Field(default_factory=list)
    iteration_id: str | None = None
    release: str | None = None
    kanban_column: str | None = None
    blocked_reason: str | None = None
    service_class: str | None = None
    client_accepted: bool = False
    client_accepted_at: datetime | None = None
    external_refs: list[dict] = Field(default_factory=list)


class ArtifactVersion(Doc):
    """Immutable once approved (section 10.1)."""

    project_id: str
    item_id: str
    item_type: ItemType
    version: int
    state: ArtifactState = ArtifactState.DRAFT
    title: str
    actor: str | None = None
    need: str | None = None
    benefit: str | None = None
    description: str | None = None
    scope_exclusions: list[str] = Field(default_factory=list)
    business_rules: list[str] = Field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    functional_notes: str | None = None
    technical_notes: str | None = None
    nfr_notes: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    open_question_ids: list[str] = Field(default_factory=list)
    risk_drivers: list[str] = Field(default_factory=list)
    design_refs: list[dict] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    provenance: Provenance = Provenance.EVIDENCE
    estimate_id: str | None = None
    author_id: str | None = None
    generated_by_role: str | None = None
    model_id: str | None = None
    prompt_template_version: str | None = None
    change_note: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    approval_event_id: str | None = None
    inherited_from_event_id: str | None = None
    superseded_at: datetime | None = None


class BacklogItemCreate(Base):
    type: ItemType
    parent_id: str | None = None
    title: str
    description: str | None = None
    actor: str | None = None
    need: str | None = None
    benefit: str | None = None
    priority: Priority = Priority.MEDIUM
    owner_id: str | None = None
    labels: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)


class BacklogItemUpdate(Base):
    """Edits always produce a new draft version; approved versions never mutate."""

    title: str | None = None
    description: str | None = None
    actor: str | None = None
    need: str | None = None
    benefit: str | None = None
    scope_exclusions: list[str] | None = None
    business_rules: list[str] | None = None
    acceptance_criteria: list[AcceptanceCriterion] | None = None
    functional_notes: str | None = None
    technical_notes: str | None = None
    nfr_notes: str | None = None
    assumptions: list[str] | None = None
    risk_drivers: list[str] | None = None
    requirement_ids: list[str] | None = None
    citations: list[Citation] | None = None
    change_note: str | None = None
    #: Mutable item level fields that do not create a version.
    priority: Priority | None = None
    owner_id: str | None = None
    labels: list[str] | None = None
    iteration_id: str | None = None
    release: str | None = None
    kanban_column: str | None = None
    blocked_reason: str | None = None
    execution_status: ExecutionStatus | None = None
    expected_rev: int | None = None


class BacklogNode(Base):
    id: str
    stable_id: str
    type: str
    parent_id: str | None = None
    title: str
    state: str
    execution_status: str
    priority: str
    current_version: int
    approved_version: int | None = None
    requires_reapproval: bool = False
    stale: bool = False
    owner_id: str | None = None
    story_points: float | None = None
    effort_hours: float = 0.0
    rollup_hours: float = 0.0
    criteria_count: int = 0
    test_count: int = 0
    open_question_count: int = 0
    children: list["BacklogNode"] = Field(default_factory=list)


BacklogNode.model_rebuild()


class RateCard(Doc):
    """Effective dated, currency aware, permission restricted (section 11.3)."""

    project_id: str | None = None
    name: str
    currency: str = "EUR"
    effective_from: date
    effective_to: date | None = None
    rates: dict[str, str] = Field(default_factory=dict)  # role -> decimal string
    non_labor_lines: list[dict] = Field(default_factory=list)
    contingency_percent: float = 0.0
    created_by: str | None = None


class EstimateCreate(Base):
    method: EstimateMethod = EstimateMethod.EXPERT
    story_points: float | None = None
    role_efforts: list[RoleEffort] = Field(default_factory=list)
    overhead_hours: float = 0.0
    low_hours: float | None = None
    likely_hours: float | None = None
    high_hours: float | None = None
    confidence_label: str = "indicative"
    assumptions: list[str] = Field(default_factory=list)
    unknown: bool = False
    spike_required: bool = False
    is_rough_parent: bool = False
    note: str | None = None
