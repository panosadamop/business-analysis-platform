"""Project knowledge: glossary, requirements, questions and traceability links
(section 7)."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.models.common import (ArtifactState, Base, Citation, Doc, Priority,
                               Provenance, Severity)


class RequirementType(StrEnum):
    BUSINESS = "business"
    FUNCTIONAL = "functional"
    NON_FUNCTIONAL = "non_functional"
    TECHNICAL = "technical"
    CONSTRAINT = "constraint"
    BUSINESS_RULE = "business_rule"
    ASSUMPTION = "assumption"
    DECISION = "decision"
    GOAL = "goal"
    STAKEHOLDER = "stakeholder"
    SCOPE_BOUNDARY = "scope_boundary"
    UX = "ux"
    DATA = "data"


class Requirement(Doc):
    project_id: str
    stable_id: str
    type: RequirementType = RequirementType.BUSINESS
    title: str
    statement: str
    rationale: str | None = None
    provenance: Provenance = Provenance.EVIDENCE
    priority: Priority = Priority.MEDIUM
    business_value: int | None = None
    #: Decision aid only, not a calibrated probability (REQ-KNOW-06).
    confidence: float = 0.5
    owner_id: str | None = None
    state: ArtifactState = ArtifactState.DRAFT
    version: int = 1
    citations: list[Citation] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    superseded_by: str | None = None
    stale: bool = False
    created_by_role: str | None = None


class RequirementVersion(Doc):
    project_id: str
    requirement_id: str
    version: int
    snapshot: dict
    state: ArtifactState
    author_id: str | None = None
    change_note: str | None = None


class QuestionStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    DEFERRED = "deferred"
    WONT_RESOLVE = "wont_resolve"


class QuestionKind(StrEnum):
    AMBIGUITY = "ambiguity"
    CONTRADICTION = "contradiction"
    DUPLICATE = "duplicate"
    MISSING_RULE = "missing_rule"
    INCOMPLETE_FLOW = "incomplete_flow"
    DESIGN_BEHAVIOUR = "design_behaviour"
    DEPENDENCY = "dependency"
    OTHER = "other"


class Question(Doc):
    project_id: str
    stable_id: str
    kind: QuestionKind = QuestionKind.AMBIGUITY
    severity: Severity = Severity.MAJOR
    title: str
    detail: str
    proposed_clarification: str | None = None
    owner_id: str | None = None
    status: QuestionStatus = QuestionStatus.OPEN
    answer: str | None = None
    answered_by: str | None = None
    answered_at: datetime | None = None
    citations: list[Citation] = Field(default_factory=list)
    related_item_ids: list[str] = Field(default_factory=list)
    related_requirement_ids: list[str] = Field(default_factory=list)
    client_visible: bool = False
    history: list[dict] = Field(default_factory=list)


class GlossaryTerm(Doc):
    project_id: str
    term: str
    definition: str
    language: str = "en"
    translations: dict[str, str] = Field(default_factory=dict)
    citations: list[Citation] = Field(default_factory=list)
    approved: bool = False


class LinkType(StrEnum):
    DERIVED_FROM = "derived_from"
    VERIFIES = "verifies"
    IMPLEMENTS = "implements"
    REFERENCES = "references"
    CONTRADICTS = "contradicts"
    DUPLICATES = "duplicates"


class EvidenceLink(Doc):
    """Many to many traceability edge (REQ-KNOW-03)."""

    project_id: str
    source_version_id: str | None = None
    source_chunk_id: str | None = None
    locator: dict | None = None
    target_type: str  # requirement | backlog_item | test_case | specification
    target_id: str
    target_version: int | None = None
    link_type: LinkType = LinkType.DERIVED_FROM
    rationale: str | None = None
    created_by: str | None = None


class DependencyLink(Doc):
    project_id: str
    from_id: str
    to_id: str
    kind: str = "blocks"  # blocks | relates | duplicates | requires
    owner_id: str | None = None
    external: bool = False
    note: str | None = None


class RequirementCreate(Base):
    type: RequirementType = RequirementType.BUSINESS
    title: str
    statement: str
    rationale: str | None = None
    provenance: Provenance = Provenance.EVIDENCE
    priority: Priority = Priority.MEDIUM
    business_value: int | None = None
    confidence: float = 0.5
    owner_id: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class RequirementUpdate(Base):
    title: str | None = None
    statement: str | None = None
    rationale: str | None = None
    type: RequirementType | None = None
    priority: Priority | None = None
    provenance: Provenance | None = None
    business_value: int | None = None
    confidence: float | None = None
    owner_id: str | None = None
    citations: list[Citation] | None = None
    tags: list[str] | None = None
    state: ArtifactState | None = None
    rev: int | None = None


class QuestionCreate(Base):
    kind: QuestionKind = QuestionKind.AMBIGUITY
    severity: Severity = Severity.MAJOR
    title: str
    detail: str
    proposed_clarification: str | None = None
    owner_id: str | None = None
    related_item_ids: list[str] = Field(default_factory=list)
    related_requirement_ids: list[str] = Field(default_factory=list)
    client_visible: bool = False


class QuestionResolve(Base):
    status: QuestionStatus
    answer: str | None = None


class EvidenceLinkCreate(Base):
    """Manually record that an artifact derives from a piece of evidence."""

    source_version_id: str
    source_chunk_id: str | None = None
    locator_kind: str = "paragraph"
    locator_value: str = ""
    target_type: str  # requirement | backlog_item | test_case | specification
    target_id: str
    target_version: int | None = None
    link_type: LinkType = LinkType.DERIVED_FROM
    rationale: str | None = None


class GlossaryTermCreate(Base):
    term: str
    definition: str
    language: str = "en"
    translations: dict[str, str] = Field(default_factory=dict)


class SearchHit(Base):
    """REQ-KNOW-07 — permission filtered keyword and semantic search."""

    chunk_id: str
    source_version_id: str
    document_id: str
    document_title: str
    snippet: str
    locator_kind: str
    locator_value: str
    score: float
    start_ms: int | None = None
    speaker: str | None = None
    language: str | None = None
