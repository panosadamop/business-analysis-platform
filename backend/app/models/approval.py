"""Approval cascade, baselines and change requests (section 10)."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.models.common import Base, Doc, Money, Severity


class Decision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class ManifestEntry(Base):
    """One exact version inside an approval bundle (REQ-APP-02)."""

    item_id: str
    stable_id: str
    item_type: str  # epic | feature | story | task | test_case | specification
    title: str
    version: int
    version_id: str
    #: Revision counter of the stored version document. A draft edited in place
    #: keeps its version number but changes this, so the manifest hash still
    #: detects the change (REQ-APP-04).
    content_rev: int = 0
    state: str
    #: Explicit when the approver named it, inherited when the cascade reached it.
    inherited: bool = True
    owner_subtree_root: str | None = None
    #: Linked artifact owned by another subtree. Reference only, never approved.
    reference_only: bool = False
    previous_approved_version: int | None = None
    changed: bool = False


class BlockerView(Base):
    kind: str
    severity: Severity
    message: str
    target_id: str | None = None
    target_title: str | None = None
    waivable: bool = True
    finding_id: str | None = None


class ManifestDiff(Base):
    added: list[ManifestEntry] = Field(default_factory=list)
    removed: list[ManifestEntry] = Field(default_factory=list)
    changed: list[ManifestEntry] = Field(default_factory=list)
    unchanged_count: int = 0


class ApprovalManifest(Doc):
    project_id: str
    root_id: str
    root_type: str
    root_title: str
    root_version: int
    entries: list[ManifestEntry] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    blockers: list[BlockerView] = Field(default_factory=list)
    diff: ManifestDiff | None = None
    estimate_totals: dict = Field(default_factory=dict)
    client_visible_entries: list[str] = Field(default_factory=list)
    previous_approval_event_id: str | None = None
    #: Hash over the exact (itemId, version) set. Submitting with a stale hash
    #: fails atomically with a refreshed diff (REQ-APP-04).
    manifest_hash: str
    generated_at: datetime
    generated_by: str | None = None


class Waiver(Base):
    blocker_kind: str
    target_id: str | None = None
    rationale: str
    waived_by: str
    waived_at: datetime


class ApprovalEvent(Doc):
    project_id: str
    manifest_id: str
    manifest_hash: str
    root_id: str
    root_type: str
    root_version: int
    decision: Decision
    decided_by: str
    decided_at: datetime
    note: str | None = None
    entries: list[ManifestEntry] = Field(default_factory=list)
    waivers: list[Waiver] = Field(default_factory=list)
    #: REQ-APP-04 — nothing counts as approved or publishable before the commit
    #: flag is set, even when a large bundle is written in stages.
    committed: bool = False
    revoked: bool = False
    revoked_by: str | None = None
    revoked_at: datetime | None = None
    revocation_reason: str | None = None
    #: Set on inherited events that point back at the parent decision.
    parent_event_id: str | None = None
    published_targets: list[str] = Field(default_factory=list)


class ApprovalSubmit(Base):
    manifest_id: str
    manifest_hash: str
    decision: Decision = Decision.APPROVE
    note: str | None = None
    waivers: list[dict] = Field(default_factory=list)


class ApprovalRevoke(Base):
    reason: str
    #: Empty revokes the whole bundle; otherwise only the listed item versions.
    item_ids: list[str] = Field(default_factory=list)


class Baseline(Doc):
    """Immutable scope, estimate, schedule and rate snapshot (section 10.3)."""

    project_id: str
    name: str
    description: str | None = None
    created_by: str | None = None
    approval_event_id: str | None = None
    items: list[dict] = Field(default_factory=list)
    totals: dict = Field(default_factory=dict)
    rate_card_id: str | None = None
    schedule: list[dict] = Field(default_factory=list)
    currency: str = "EUR"
    hours_per_person_day: float = 8.0
    locked: bool = True


class BaselineCreate(Base):
    name: str
    description: str | None = None
    approval_event_id: str | None = None


class BaselineComparison(Base):
    baseline_id: str
    baseline_name: str
    as_of: datetime
    added: list[dict] = Field(default_factory=list)
    removed: list[dict] = Field(default_factory=list)
    changed: list[dict] = Field(default_factory=list)
    totals_baseline: dict = Field(default_factory=dict)
    totals_current: dict = Field(default_factory=dict)
    delta: dict = Field(default_factory=dict)


class ChangeRequestStatus(StrEnum):
    PROPOSED = "proposed"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class ChangeRequest(Doc):
    project_id: str
    stable_id: str
    title: str
    reason: str
    status: ChangeRequestStatus = ChangeRequestStatus.PROPOSED
    baseline_id: str | None = None
    raised_by: str | None = None
    origin: str = "internal"  # internal | client | connector
    evidence_refs: list[dict] = Field(default_factory=list)
    affected_item_ids: list[str] = Field(default_factory=list)
    effort_delta_hours: float = 0.0
    cost_delta: Money | None = None
    date_impact_days: float = 0.0
    decision_note: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None


class ChangeRequestCreate(Base):
    title: str
    reason: str
    baseline_id: str | None = None
    affected_item_ids: list[str] = Field(default_factory=list)
    effort_delta_hours: float = 0.0
    date_impact_days: float = 0.0
    origin: str = "internal"
    evidence_refs: list[dict] = Field(default_factory=list)


class ChangeRequestDecide(Base):
    status: ChangeRequestStatus
    decision_note: str | None = None
