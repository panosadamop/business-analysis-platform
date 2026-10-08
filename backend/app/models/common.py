"""Shared enumerations and base model types."""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.core.utils import money, new_id, utcnow


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def _validate_email(value: str) -> str:
    """Accept internal company domains such as ``.local`` that public email
    validators reject, while still refusing malformed addresses."""
    normalised = value.strip().lower()
    if not _EMAIL_RE.match(normalised):
        raise ValueError("not a valid email address")
    return normalised


#: Email address type used across the domain models.
Email = Annotated[str, AfterValidator(_validate_email)]


class Base(BaseModel):
    """All API and persistence models use camelCase on the wire."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        use_enum_values=True,
        ser_json_timedelta="float",
    )


class Doc(Base):
    id: str = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    #: Optimistic concurrency token (section 18).
    rev: int = 0


T = TypeVar("T")


class Page(Base, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class Language(StrEnum):
    EL = "el"
    EN = "en"


class DeliveryMethod(StrEnum):
    SCRUM = "scrum"
    KANBAN = "kanban"


class Classification(StrEnum):
    """Data classification drives the egress gate (section 8.3)."""

    RESTRICTED = "restricted"
    CONFIDENTIAL = "confidential"
    SHAREABLE = "shareable"


class ArtifactState(StrEnum):
    """Section 10.1. Approved versions are immutable."""

    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class ItemType(StrEnum):
    """Canonical hierarchy: Project -> Epic -> Feature -> Story (-> Task)."""

    EPIC = "epic"
    FEATURE = "feature"
    STORY = "story"
    TASK = "task"


ITEM_PARENT: dict[ItemType, ItemType | None] = {
    ItemType.EPIC: None,
    ItemType.FEATURE: ItemType.EPIC,
    ItemType.STORY: ItemType.FEATURE,
    ItemType.TASK: ItemType.STORY,
}

ITEM_ORDER: list[ItemType] = [ItemType.EPIC, ItemType.FEATURE, ItemType.STORY, ItemType.TASK]


class Severity(StrEnum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"


class Priority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Provenance(StrEnum):
    """REQ-KNOW-06 — evidence, analyst assumption and AI suggestion stay apart."""

    EVIDENCE = "evidence"
    ASSUMPTION = "assumption"
    AI_SUGGESTION = "ai_suggestion"
    CLIENT_DECISION = "client_decision"


class ExecutionStatus(StrEnum):
    """Delivery state, tracked separately from approval (REQ-PLAN-05)."""

    NOT_STARTED = "not_started"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    IN_REVIEW = "in_review"
    DONE = "done"
    CANCELLED = "cancelled"


class AnalystRole(StrEnum):
    BA = "business_analyst"
    UX = "ux_analyst"
    DATA = "data_analyst"
    TA = "technical_analyst"
    QA = "qa_analyst"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL = "partial"
    PAUSED = "paused"


class Money(Base):
    """Decimal safe money. Amounts are carried as strings, never as floats."""

    amount: str = "0.00"
    currency: str = "EUR"

    @classmethod
    def of(cls, amount: Decimal | float | int | str, currency: str = "EUR") -> "Money":
        return cls(amount=str(money(amount)), currency=currency)

    @property
    def value(self) -> Decimal:
        return Decimal(self.amount)

    def plus(self, other: "Money") -> "Money":
        if other.currency != self.currency:
            raise ValueError("refusing to combine currencies without an exchange snapshot")
        return Money.of(self.value + other.value, self.currency)


class EvidenceLocator(Base):
    """Section 6.1 — how a claim points back into a source."""

    source_version_id: str
    kind: str  # paragraph | page | cell_range | timestamp | node | row | schema_path
    value: str
    label: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    speaker: str | None = None
    page: int | None = None
    confidence: float | None = None


class Citation(Base):
    locator: EvidenceLocator
    quote: str | None = None
    note: str | None = None


class Warning(Base):
    code: str
    message: str
    details: dict[str, Any] | None = None


def touch(doc: dict[str, Any]) -> dict[str, Any]:
    doc["updatedAt"] = utcnow()
    return doc
