"""Connector adapter contract (section 14.1).

A connector discovers what the destination actually supports before any mapping
is configured. Nothing is assumed about native hierarchy levels: the discovery
result drives the mapping, and anything the destination cannot carry stays in
the internal canonical model and is shown in the publication preview.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.models.integration import CapabilityReport, FieldRule, TypeMapping


@dataclass
class Credential:
    """Credentials stay encrypted on company infrastructure and never enter AI context."""

    base_url: str | None = None
    email: str | None = None
    token: str | None = None
    organization: str | None = None
    project: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.token)


@dataclass
class RemoteItem:
    external_id: str
    external_key: str | None = None
    url: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    revision: str | None = None


@dataclass
class PublishOutcome:
    internal_id: str
    status: str  # created | updated | skipped | failed | conflict
    external_id: str | None = None
    external_key: str | None = None
    url: str | None = None
    message: str | None = None
    unsupported_fields: list[str] = field(default_factory=list)


class ConnectorAdapter(ABC):
    provider: str = "generic"

    def __init__(self, credential: Credential) -> None:
        self.credential = credential

    @property
    def configured(self) -> bool:
        return self.credential.configured

    @abstractmethod
    async def discover(self) -> CapabilityReport: ...

    @abstractmethod
    async def publish(self, item: dict[str, Any], *, type_mapping: TypeMapping,
                      field_rules: list[FieldRule],
                      external_id: str | None) -> PublishOutcome: ...

    @abstractmethod
    async def fetch_changes(self, since: str | None) -> list[RemoteItem]: ...

    async def health(self) -> tuple[str, str]:
        if not self.configured:
            return "not_configured", "No credentials are stored for this connector"
        return "unknown", "Health is evaluated on the next synchronisation"

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        """Each provider uses its own supported authenticity mechanism."""
        return False


def unsupported(message: str) -> PublishOutcome:
    return PublishOutcome(internal_id="", status="failed", message=message)
