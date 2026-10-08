"""Audit trail. Structured, correlated and free of raw content (NFR-11)."""
from __future__ import annotations

from typing import Any

from app.core.utils import utcnow
from app.models.collaboration import AuditEvent
from app.repositories import audit_events


async def record(action: str, *, project_id: str | None = None, actor_id: str | None = None,
                 actor_email: str | None = None, object_type: str | None = None,
                 object_id: str | None = None, object_version: int | None = None,
                 detail: dict[str, Any] | None = None,
                 correlation_id: str | None = None) -> AuditEvent:
    event = AuditEvent(
        project_id=project_id,
        actor_id=actor_id,
        actor_email=actor_email,
        action=action,
        object_type=object_type,
        object_id=object_id,
        object_version=object_version,
        at=utcnow(),
        detail=detail or {},
        correlation_id=correlation_id,
    )
    await audit_events.insert(event)
    return event


async def history(project_id: str, *, object_id: str | None = None,
                  limit: int = 100, offset: int = 0) -> list[AuditEvent]:
    query: dict[str, Any] = {"projectId": project_id}
    if object_id:
        query["objectId"] = object_id
    return await audit_events.list(query, sort=[("at", -1)], limit=limit, offset=offset)
