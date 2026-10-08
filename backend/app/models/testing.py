"""Test cases, Gherkin and the project testbook (section 13)."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.models.common import ArtifactState, Base, Doc, Priority


class TestType(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    BOUNDARY = "boundary"
    VALIDATION = "validation"
    PERMISSIONS = "permissions"
    INTEGRATION = "integration"
    NON_FUNCTIONAL = "non_functional"
    END_TO_END = "end_to_end"
    ACCEPTANCE = "acceptance"


class TestStep(Base):
    ordinal: int
    action: str
    expected: str | None = None


class GherkinStep(Base):
    keyword: str  # Given | When | Then | And | But
    text: str


class GherkinScenario(Base):
    """Canonical structure stored once; translations are display versions only."""

    name: str
    tags: list[str] = Field(default_factory=list)
    outline: bool = False
    steps: list[GherkinStep] = Field(default_factory=list)
    examples_header: list[str] = Field(default_factory=list)
    examples_rows: list[list[str]] = Field(default_factory=list)


class GherkinFeature(Base):
    name: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    background: list[GherkinStep] = Field(default_factory=list)
    scenarios: list[GherkinScenario] = Field(default_factory=list)
    dialect: str = "en"


class TestCase(Doc):
    project_id: str
    stable_id: str
    title: str
    objective: str | None = None
    story_id: str | None = None
    story_version: int | None = None
    criterion_ids: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)
    test_type: TestType = TestType.POSITIVE
    priority: Priority = Priority.MEDIUM
    preconditions: list[str] = Field(default_factory=list)
    synthetic_data: dict = Field(default_factory=dict)
    steps: list[TestStep] = Field(default_factory=list)
    expected_results: list[str] = Field(default_factory=list)
    environment_assumptions: list[str] = Field(default_factory=list)
    gherkin: GherkinFeature | None = None
    tags: list[str] = Field(default_factory=list)
    state: ArtifactState = ArtifactState.DRAFT
    version: int = 1
    #: Generation never marks a test as passed (section 13).
    review_state: str = "pending_review"
    generated_by_role: str | None = None
    validation: dict = Field(default_factory=dict)
    owner_subtree_root: str | None = None


class TestVersion(Doc):
    project_id: str
    test_case_id: str
    version: int
    snapshot: dict
    state: ArtifactState
    author_id: str | None = None


class Testbook(Doc):
    project_id: str
    name: str
    version: int = 1
    purpose: str | None = None
    release_scope: str | None = None
    manifest: list[dict] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    environments: list[dict] = Field(default_factory=list)
    entry_criteria: list[str] = Field(default_factory=list)
    exit_criteria: list[str] = Field(default_factory=list)
    suites: list[dict] = Field(default_factory=list)
    coverage: dict = Field(default_factory=dict)
    gaps: list[dict] = Field(default_factory=list)
    state: ArtifactState = ArtifactState.DRAFT
    assembled_by: str | None = None
    assembled_at: datetime | None = None


class CoverageRow(Base):
    criterion_id: str
    criterion_text: str
    item_id: str
    item_stable_id: str
    item_title: str
    test_ids: list[str] = Field(default_factory=list)
    covered: bool = False


class CoverageMatrix(Base):
    rows: list[CoverageRow] = Field(default_factory=list)
    uncovered_criteria: int = 0
    unlinked_tests: list[dict] = Field(default_factory=list)
    covered_percent: float = 0.0
    total_criteria: int = 0
    total_tests: int = 0


class TestCaseCreate(Base):
    title: str
    objective: str | None = None
    story_id: str | None = None
    criterion_ids: list[str] = Field(default_factory=list)
    test_type: TestType = TestType.POSITIVE
    priority: Priority = Priority.MEDIUM
    preconditions: list[str] = Field(default_factory=list)
    steps: list[TestStep] = Field(default_factory=list)
    expected_results: list[str] = Field(default_factory=list)
    gherkin_text: str | None = None
    tags: list[str] = Field(default_factory=list)


class TestCaseUpdate(Base):
    title: str | None = None
    objective: str | None = None
    criterion_ids: list[str] | None = None
    test_type: TestType | None = None
    priority: Priority | None = None
    preconditions: list[str] | None = None
    steps: list[TestStep] | None = None
    expected_results: list[str] | None = None
    environment_assumptions: list[str] | None = None
    gherkin_text: str | None = None
    tags: list[str] | None = None
    review_state: str | None = None
    expected_rev: int | None = None


class GherkinValidation(Base):
    valid: bool
    dialect: str = "en"
    errors: list[dict] = Field(default_factory=list)
    warnings: list[dict] = Field(default_factory=list)
    scenario_count: int = 0
    tags: list[str] = Field(default_factory=list)
