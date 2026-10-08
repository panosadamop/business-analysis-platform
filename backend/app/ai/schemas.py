"""Versioned output contracts for the analyst roles (section 8.2).

Every role output is validated against these schemas before anything is saved.
Invalid output is a stage failure, not a silently empty analysis.
"""
from __future__ import annotations

from pydantic import Field, ValidationError

from app.models.common import Base, Provenance, Severity

SCHEMA_VERSION = "1.0"


class CitationOut(Base):
    source_version_id: str | None = None
    locator_kind: str = "paragraph"
    locator_value: str = ""
    quote: str | None = None


class RequirementOut(Base):
    title: str
    statement: str
    type: str = "business"
    priority: str = "medium"
    provenance: Provenance = Provenance.EVIDENCE
    confidence: float = 0.5
    rationale: str | None = None
    citations: list[CitationOut] = Field(default_factory=list)


class QuestionOut(Base):
    title: str
    detail: str
    kind: str = "ambiguity"
    severity: Severity = Severity.MAJOR
    proposed_clarification: str | None = None
    citations: list[CitationOut] = Field(default_factory=list)


class CriterionOut(Base):
    text: str
    outcome_level: bool = False


class StoryOut(Base):
    title: str
    actor: str | None = None
    need: str | None = None
    benefit: str | None = None
    description: str | None = None
    acceptance_criteria: list[CriterionOut] = Field(default_factory=list)
    business_rules: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    citations: list[CitationOut] = Field(default_factory=list)
    provenance: Provenance = Provenance.EVIDENCE
    estimate_hint_hours: float | None = None
    story_points_hint: float | None = None
    risk_drivers: list[str] = Field(default_factory=list)


class FeatureOut(Base):
    title: str
    description: str | None = None
    acceptance_criteria: list[CriterionOut] = Field(default_factory=list)
    stories: list[StoryOut] = Field(default_factory=list)


class EpicOut(Base):
    title: str
    description: str | None = None
    acceptance_criteria: list[CriterionOut] = Field(default_factory=list)
    features: list[FeatureOut] = Field(default_factory=list)


class BAOutput(Base):
    """Business analyst stage contract."""

    schema_version: str = SCHEMA_VERSION
    summary: str = ""
    goals: list[str] = Field(default_factory=list)
    stakeholders: list[str] = Field(default_factory=list)
    scope_boundaries: list[str] = Field(default_factory=list)
    glossary: list[dict] = Field(default_factory=list)
    business_rules: list[RequirementOut] = Field(default_factory=list)
    requirements: list[RequirementOut] = Field(default_factory=list)
    questions: list[QuestionOut] = Field(default_factory=list)
    epics: list[EpicOut] = Field(default_factory=list)
    functional_specification: str | None = None


class FindingOut(Base):
    title: str
    rationale: str
    severity: Severity = Severity.MAJOR
    category: str = "quality"
    recommendation: str | None = None
    target_stable_id: str | None = None
    blocking: bool = False
    citations: list[CitationOut] = Field(default_factory=list)


class DataEntityOut(Base):
    name: str
    description: str | None = None
    fields: list[dict] = Field(default_factory=list)
    relationships: list[dict] = Field(default_factory=list)
    privacy_classification: str = "internal"
    lifecycle: str | None = None


class ApiOperationOut(Base):
    method: str
    path: str
    summary: str
    auth: str = "bearer"
    request_schema: dict = Field(default_factory=dict)
    response_schema: dict = Field(default_factory=dict)
    errors: list[dict] = Field(default_factory=list)
    idempotent: bool = False
    paginated: bool = False


class TAOutput(Base):
    """Technical analyst stage contract."""

    schema_version: str = SCHEMA_VERSION
    findings: list[FindingOut] = Field(default_factory=list)
    technical_notes: dict[str, str] = Field(default_factory=dict)
    nfr_requirements: list[RequirementOut] = Field(default_factory=list)
    dependencies: list[dict] = Field(default_factory=list)
    effort_drivers: list[dict] = Field(default_factory=list)
    data_entities: list[DataEntityOut] = Field(default_factory=list)
    api_operations: list[ApiOperationOut] = Field(default_factory=list)
    process_diagrams: list[dict] = Field(default_factory=list)
    architecture_proposals: list[str] = Field(default_factory=list)


class GherkinOut(Base):
    feature: str
    scenario: str
    tags: list[str] = Field(default_factory=list)
    given: list[str] = Field(default_factory=list)
    when: list[str] = Field(default_factory=list)
    then: list[str] = Field(default_factory=list)
    examples_header: list[str] = Field(default_factory=list)
    examples_rows: list[list[str]] = Field(default_factory=list)


class TestOut(Base):
    title: str
    story_stable_id: str | None = None
    criterion_index: int | None = None
    objective: str | None = None
    test_type: str = "positive"
    priority: str = "medium"
    preconditions: list[str] = Field(default_factory=list)
    steps: list[dict] = Field(default_factory=list)
    expected_results: list[str] = Field(default_factory=list)
    environment_assumptions: list[str] = Field(default_factory=list)
    gherkin: GherkinOut | None = None


class QAOutput(Base):
    """QA analyst stage contract."""

    schema_version: str = SCHEMA_VERSION
    findings: list[FindingOut] = Field(default_factory=list)
    refined_criteria: dict[str, list[str]] = Field(default_factory=dict)
    tests: list[TestOut] = Field(default_factory=list)
    coverage_notes: list[str] = Field(default_factory=list)


class PersonaOut(Base):
    name: str
    goals: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    citations: list[CitationOut] = Field(default_factory=list)


class JourneyOut(Base):
    title: str
    persona: str | None = None
    steps: list[str] = Field(default_factory=list)
    mermaid: str | None = None
    story_stable_ids: list[str] = Field(default_factory=list)


class ScreenOut(Base):
    name: str
    purpose: str
    story_stable_ids: list[str] = Field(default_factory=list)
    #: The states the screen must design for: empty, loading, error, success...
    states: list[str] = Field(default_factory=list)
    key_elements: list[str] = Field(default_factory=list)


class UXOutput(Base):
    """UX analyst stage contract."""

    schema_version: str = SCHEMA_VERSION
    findings: list[FindingOut] = Field(default_factory=list)
    personas: list[PersonaOut] = Field(default_factory=list)
    journeys: list[JourneyOut] = Field(default_factory=list)
    screens: list[ScreenOut] = Field(default_factory=list)
    ux_requirements: list[RequirementOut] = Field(default_factory=list)


class DataQualityRuleOut(Base):
    entity: str
    field: str | None = None
    rule: str
    severity: Severity = Severity.MAJOR
    citations: list[CitationOut] = Field(default_factory=list)


class MetricOut(Base):
    name: str
    definition: str
    formula: str | None = None
    source_entities: list[str] = Field(default_factory=list)
    citations: list[CitationOut] = Field(default_factory=list)


class RetentionOut(Base):
    entity: str
    classification: str = "internal"
    retention: str
    deletion: str | None = None
    citations: list[CitationOut] = Field(default_factory=list)


class MigrationOut(Base):
    source: str
    target: str | None = None
    notes: str
    citations: list[CitationOut] = Field(default_factory=list)


class DataOutput(Base):
    """Data analyst stage contract."""

    schema_version: str = SCHEMA_VERSION
    findings: list[FindingOut] = Field(default_factory=list)
    data_requirements: list[RequirementOut] = Field(default_factory=list)
    quality_rules: list[DataQualityRuleOut] = Field(default_factory=list)
    metrics: list[MetricOut] = Field(default_factory=list)
    retention: list[RetentionOut] = Field(default_factory=list)
    migration: list[MigrationOut] = Field(default_factory=list)


ROLE_SCHEMAS = {
    "business_analyst": BAOutput,
    "ux_analyst": UXOutput,
    "data_analyst": DataOutput,
    "technical_analyst": TAOutput,
    "qa_analyst": QAOutput,
}


def validate(role: str, payload: dict) -> Base:
    """Validate a role payload. Raises ``ValidationError`` on contract breach."""
    model = ROLE_SCHEMAS[role]
    return model(**payload)


def json_schema(role: str) -> dict:
    return ROLE_SCHEMAS[role].model_json_schema(by_alias=True)


__all__ = ["BAOutput", "UXOutput", "DataOutput", "TAOutput", "QAOutput", "validate", "json_schema",
           "SCHEMA_VERSION", "ValidationError", "ROLE_SCHEMAS"]
