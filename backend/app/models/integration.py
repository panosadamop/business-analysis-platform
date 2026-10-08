"""Bidirectional connector models (section 14)."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.models.common import Base, Doc, JobStatus


class Provider(StrEnum):
    JIRA = "jira"
    AZURE_DEVOPS = "azure_devops"
    ASANA = "asana"


class FieldOwnership(StrEnum):
    """Section 14.2 — who is authoritative for a field."""

    INTERNAL = "internal"
    EXTERNAL = "external"
    THREE_WAY = "three_way"
    IGNORE = "ignore"


class FieldRule(Base):
    canonical_field: str
    external_field: str | None = None
    ownership: FieldOwnership = FieldOwnership.INTERNAL
    direction: str = "outbound"  # outbound | inbound | both
    transform: str | None = None
    required_remote: bool = False
    supported: bool = True
    note: str | None = None


class TypeMapping(Base):
    canonical_type: str  # epic | feature | story | task | test_case | criterion
    external_type: str | None = None
    strategy: str = "native"  # native | link | metadata | description | unsupported
    note: str | None = None


class CapabilityReport(Base):
    """Discovery output presented before mapping approval (section 14.1)."""

    provider: str
    discovered_at: datetime
    projects: list[dict] = Field(default_factory=list)
    item_types: list[dict] = Field(default_factory=list)
    fields: list[dict] = Field(default_factory=list)
    transitions: list[dict] = Field(default_factory=list)
    identities: list[dict] = Field(default_factory=list)
    hierarchy_levels: list[str] = Field(default_factory=list)
    supports_worklogs: bool = False
    supports_webhooks: bool = False
    limitations: list[str] = Field(default_factory=list)
    suggested_type_mappings: list[TypeMapping] = Field(default_factory=list)
    suggested_field_rules: list[FieldRule] = Field(default_factory=list)


class Integration(Doc):
    project_id: str
    provider: Provider
    name: str
    base_url: str | None = None
    external_project_key: str | None = None
    #: Reference into the secret store. Credentials never enter AI context.
    secret_ref: str | None = None
    enabled: bool = False
    is_primary: bool = False
    mapping_approved: bool = False
    mapping_approved_by: str | None = None
    mapping_approved_at: datetime | None = None
    type_mappings: list[TypeMapping] = Field(default_factory=list)
    field_rules: list[FieldRule] = Field(default_factory=list)
    identity_map: dict[str, str] = Field(default_factory=dict)
    capability_report: CapabilityReport | None = None
    webhook_secret_ref: str | None = None
    use_polling: bool = True
    last_sync_at: datetime | None = None
    last_error: str | None = None
    health: str = "unknown"  # healthy | degraded | failing | unknown
    allow_deletes: bool = False


class ExternalMapping(Doc):
    project_id: str
    integration_id: str
    internal_id: str
    internal_type: str
    external_id: str
    external_key: str | None = None
    external_url: str | None = None
    sync_revision: int = 0
    last_payload_hash: str | None = None
    #: Last values both sides agreed on, used for three way conflict detection.
    last_common_values: dict = Field(default_factory=dict)
    tombstoned: bool = False
    last_synced_at: datetime | None = None


class ConflictField(Base):
    field: str
    internal_value: object | None = None
    external_value: object | None = None
    common_value: object | None = None
    resolution: str | None = None  # internal | external | manual


class SyncEvent(Doc):
    project_id: str
    integration_id: str
    event_id: str
    direction: str  # outbound | inbound
    kind: str
    internal_id: str | None = None
    external_id: str | None = None
    status: str = "pending"  # pending | applied | conflict | failed | ignored
    conflicts: list[ConflictField] = Field(default_factory=list)
    payload_ref: dict | None = None
    error: str | None = None
    origin_marker: str | None = None
    received_at: datetime | None = None


class OutboxJob(Doc):
    """Transactional outbox with idempotency keys and backoff (section 14.2)."""

    project_id: str
    integration_id: str
    kind: str
    payload: dict = Field(default_factory=dict)
    idempotency_key: str | None = None
    status: JobStatus = JobStatus.QUEUED
    attempts: int = 0
    max_attempts: int = 5
    available_at: datetime | None = None
    last_error: str | None = None
    dead_lettered: bool = False
    approval_event_id: str | None = None
    results: list[dict] = Field(default_factory=list)


class PublicationPreviewRow(Base):
    internal_id: str
    stable_id: str
    title: str
    canonical_type: str
    external_type: str | None = None
    action: str  # create | update | skip | unsupported
    mapped_fields: dict = Field(default_factory=dict)
    #: Fields that stay internal because the destination cannot carry them.
    unsupported_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    external_id: str | None = None


class PublicationPreview(Base):
    integration_id: str
    provider: str
    approval_event_id: str | None = None
    rows: list[PublicationPreviewRow] = Field(default_factory=list)
    blocked: list[dict] = Field(default_factory=list)
    hierarchy_note: str | None = None
    information_loss: bool = False
    total: int = 0


class IntegrationCreate(Base):
    provider: Provider
    name: str
    base_url: str | None = None
    external_project_key: str | None = None
    credential: dict = Field(default_factory=dict)
    use_polling: bool = True


class IntegrationUpdate(Base):
    name: str | None = None
    base_url: str | None = None
    external_project_key: str | None = None
    enabled: bool | None = None
    is_primary: bool | None = None
    type_mappings: list[TypeMapping] | None = None
    field_rules: list[FieldRule] | None = None
    identity_map: dict[str, str] | None = None
    use_polling: bool | None = None
    allow_deletes: bool | None = None
    credential: dict | None = None


class PublishRequest(Base):
    approval_event_id: str
    item_ids: list[str] = Field(default_factory=list)
    idempotency_key: str | None = None
    dry_run: bool = False


class ConflictResolution(Base):
    sync_event_id: str
    resolutions: dict[str, str] = Field(default_factory=dict)  # field -> internal|external
    note: str | None = None
