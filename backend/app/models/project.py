"""Project aggregate: policy, calendar, languages and delivery settings."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import Field, field_validator

from app.models.common import (AnalystRole, Base, Classification, DeliveryMethod, Doc,
                               Language, Money)

#: The analyst stages in the order an analysis run executes them: the UX and
#: data analysts build on the business backlog, the technical analyst reviews
#: feasibility across all of it, and QA tests the result.
ANALYST_ORDER = [AnalystRole.BA, AnalystRole.UX, AnalystRole.DATA,
                 AnalystRole.TA, AnalystRole.QA]

#: What a project uses unless someone chooses otherwise. The UX and data
#: analysts are opt in, so adding them never changes an existing project's runs.
DEFAULT_ANALYSTS = [AnalystRole.BA, AnalystRole.TA, AnalystRole.QA]


def _normalise_analysts(value: list[AnalystRole] | None) -> list[AnalystRole] | None:
    """At least one analyst, no repeats, in run order."""
    if value is None:
        return None
    chosen = {AnalystRole(role) for role in value}
    if not chosen:
        raise ValueError("A project needs at least one analyst")
    return [role for role in ANALYST_ORDER if role in chosen]


class AIPolicy(Base):
    """Section 8.3. Cloud is disabled by default for every project."""

    cloud_enabled: bool = False
    local_only: bool = True
    #: Highest classification that may ever leave company infrastructure.
    max_cloud_classification: Classification = Classification.SHAREABLE
    allow_cloud_for_roles: list[str] = Field(default_factory=list)
    sanitize_payloads: bool = True
    #: Human readable record of what the project agreed may be disclosed.
    permitted_disclosure_note: str | None = None
    local_model: str | None = None
    cloud_model: str | None = None
    monthly_budget: Money | None = None
    #: Transcription, OCR, embeddings and indexing are local by default.
    local_transcription: bool = True
    local_ocr: bool = True
    local_embeddings: bool = True


class WorkingCalendar(Base):
    timezone: str = "Europe/Athens"
    #: ISO weekday numbers, 1 = Monday.
    working_days: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5])
    hours_per_person_day: float = 8.0
    holidays: list[date] = Field(default_factory=list)
    #: Explicitly configured, never silently applied twice (section 11.3).
    focus_factor: float = 1.0
    allocation_includes_focus: bool = False


class QualityGates(Base):
    require_acceptance_criteria: bool = True
    require_tests_for_stories: bool = True
    block_on_critical_findings: bool = True
    block_on_unresolved_critical_questions: bool = True
    require_client_acceptance: bool = False
    max_correction_cycles: int = 3


class Project(Doc):
    key: str
    name: str
    client_name: str | None = None
    description: str | None = None
    languages: list[Language] = Field(default_factory=lambda: [Language.EN])
    output_language: Language = Language.EN
    delivery_method: DeliveryMethod = DeliveryMethod.SCRUM
    default_classification: Classification = Classification.CONFIDENTIAL
    calendar: WorkingCalendar = Field(default_factory=WorkingCalendar)
    ai_policy: AIPolicy = Field(default_factory=AIPolicy)
    quality_gates: QualityGates = Field(default_factory=QualityGates)
    currency: str = "EUR"
    #: The analysts an analysis run uses for this project. Projects stored
    #: before this setting existed get the defaults.
    enabled_analysts: list[AnalystRole] = Field(default_factory=lambda: list(DEFAULT_ANALYSTS))
    archived: bool = False
    owner_id: str | None = None
    #: Primary delivery destination; multiple destinations need explicit routing.
    primary_integration_id: str | None = None
    started_on: date | None = None
    target_end_on: date | None = None


class ProjectCreate(Base):
    key: str
    name: str
    client_name: str | None = None
    description: str | None = None
    languages: list[Language] = Field(default_factory=lambda: [Language.EN])
    output_language: Language = Language.EN
    delivery_method: DeliveryMethod = DeliveryMethod.SCRUM
    default_classification: Classification = Classification.CONFIDENTIAL
    currency: str = "EUR"
    calendar: WorkingCalendar | None = None
    ai_policy: AIPolicy | None = None
    enabled_analysts: list[AnalystRole] = Field(default_factory=lambda: list(DEFAULT_ANALYSTS))

    _analysts = field_validator("enabled_analysts")(_normalise_analysts)


class ProjectUpdate(Base):
    name: str | None = None
    client_name: str | None = None
    description: str | None = None
    languages: list[Language] | None = None
    output_language: Language | None = None
    delivery_method: DeliveryMethod | None = None
    default_classification: Classification | None = None
    calendar: WorkingCalendar | None = None
    ai_policy: AIPolicy | None = None
    quality_gates: QualityGates | None = None
    currency: str | None = None
    enabled_analysts: list[AnalystRole] | None = None
    archived: bool | None = None
    primary_integration_id: str | None = None
    started_on: date | None = None
    target_end_on: date | None = None

    _analysts = field_validator("enabled_analysts")(_normalise_analysts)


class ProjectHealth(Base):
    project_id: str
    key: str
    name: str
    client_name: str | None = None
    delivery_method: str
    open_critical_questions: int = 0
    pending_approvals: int = 0
    unresolved_findings: int = 0
    stories: int = 0
    approved_stories: int = 0
    estimated_hours: float = 0.0
    actual_hours: float = 0.0
    budget: Money | None = None
    forecast_cost: Money | None = None
    next_milestone: str | None = None
    next_milestone_date: datetime | None = None
    connector_health: str = "not_configured"
    local_only: bool = True
