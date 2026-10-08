"""Connector configuration, publication and bidirectional synchronisation
(section 14.2).

Guarantees implemented here:

* only approved, non revoked versions may be published (REQ-APP-08);
* publication runs through a transactional outbox with idempotency keys,
  retries with backoff and dead lettering;
* webhook and job replays are deduplicated, so a replay creates no duplicate
  external item, worklog or update loop (AT-08);
* incoming operational status and assignment changes update delivery state
  immediately, while incoming specification, criteria or material estimate
  changes create a reviewable draft or change request and never inherit
  approval;
* concurrent changes surface as a field level three way conflict instead of a
  silent last write wins (AT-09);
* a partial remote batch is never reported as an atomic successful publication.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from app.core.errors import ConflictState, Forbidden, NotFound, ValidationFailed
from app.core.utils import new_id, stable_hash, utcnow
from app.integrations.adapters.asana import AsanaAdapter
from app.integrations.adapters.azure_devops import AzureDevOpsAdapter
from app.integrations.adapters.jira import JiraAdapter
from app.integrations.base import ConnectorAdapter, Credential
from app.models.approval import ChangeRequest
from app.models.common import ExecutionStatus, JobStatus
from app.models.integration import (ConflictField, ExternalMapping, Integration,
                                    IntegrationCreate, IntegrationUpdate,
                                    OutboxJob, Provider, PublicationPreview,
                                    PublicationPreviewRow, PublishRequest,
                                    SyncEvent, TypeMapping)
from app.models.planning import Worklog
from app.repositories import (approval_events, artifact_versions, backlog_items,
                              change_requests, estimates, external_mappings,
                              integrations, outbox, projects, sync_events,
                              worklogs)
from app.services import audit, secrets
from app.services.estimation import total_hours

log = logging.getLogger(__name__)

ADAPTERS: dict[str, type[ConnectorAdapter]] = {
    Provider.JIRA: JiraAdapter,
    Provider.AZURE_DEVOPS: AzureDevOpsAdapter,
    Provider.ASANA: AsanaAdapter,
}

#: Origin marker written on every outbound payload so an echoed webhook is
#: recognised without relying on timestamps alone.
ORIGIN_MARKER = "ai-analysis-team"


async def adapter_for(integration: Integration) -> ConnectorAdapter:
    credential = Credential(base_url=integration.base_url,
                            project=integration.external_project_key)
    if integration.secret_ref:
        try:
            stored = await secrets.read(integration.secret_ref)
            credential = Credential(
                base_url=stored.get("baseUrl") or integration.base_url,
                email=stored.get("email"), token=stored.get("token"),
                organization=stored.get("organization"),
                project=stored.get("project") or integration.external_project_key)
        except NotFound:
            log.warning("integration %s references a missing secret", integration.id)
    return ADAPTERS[str(integration.provider)](credential)


async def create(project_id: str, payload: IntegrationCreate, *,
                 actor_id: str) -> Integration:
    secret_ref = None
    if payload.credential:
        secret_ref = await secrets.store(payload.credential, project_id=project_id)
    integration = Integration(
        project_id=project_id, provider=payload.provider, name=payload.name,
        base_url=payload.base_url, external_project_key=payload.external_project_key,
        secret_ref=secret_ref, use_polling=payload.use_polling,
        health="not_configured" if not secret_ref else "unknown",
    )
    await integrations.insert(integration)
    await audit.record("integration.created", project_id=project_id, actor_id=actor_id,
                       object_type="integration", object_id=integration.id,
                       detail={"provider": str(payload.provider)})
    return integration


async def update(project_id: str, integration_id: str, payload: IntegrationUpdate, *,
                 actor_id: str) -> Integration:
    integration = await integrations.require(integration_id, projectId=project_id)
    changes: dict[str, Any] = {}
    data = payload.model_dump(exclude_unset=True, by_alias=True)
    credential = data.pop("credential", None)
    if credential:
        changes["secretRef"] = await secrets.store(credential, project_id=project_id,
                                                   secret_ref=integration.secret_ref)
    mapping_fields = {"typeMappings", "fieldRules"}
    for key, value in data.items():
        if value is None:
            continue
        changes[key] = value
    if mapping_fields & set(changes):
        # Changing a mapping invalidates its approval; it has to be reviewed again.
        changes["mappingApproved"] = False
        changes["mappingApprovedBy"] = None
        changes["mappingApprovedAt"] = None
    if changes.get("isPrimary"):
        await integrations.raw_update({"projectId": project_id,
                                       "_id": {"$ne": integration_id}},
                                      {"$set": {"isPrimary": False}})
        await projects.update(project_id, {"primaryIntegrationId": integration_id})
    updated = await integrations.update(integration_id, changes, projectId=project_id)
    await audit.record("integration.updated", project_id=project_id, actor_id=actor_id,
                       object_type="integration", object_id=integration_id,
                       detail={"fields": sorted(changes)})
    return updated


async def discover(project_id: str, integration_id: str, *, actor_id: str) -> Integration:
    integration = await integrations.require(integration_id, projectId=project_id)
    adapter = await adapter_for(integration)
    report = await adapter.discover()
    changes = {
        "capabilityReport": report.model_dump(by_alias=True),
        "health": "healthy" if adapter.configured else "not_configured",
    }
    if not integration.type_mappings:
        changes["typeMappings"] = [t.model_dump(by_alias=True)
                                   for t in report.suggested_type_mappings]
    if not integration.field_rules:
        changes["fieldRules"] = [f.model_dump(by_alias=True)
                                 for f in report.suggested_field_rules]
    updated = await integrations.update(integration_id, changes, projectId=project_id)
    await audit.record("integration.discovered", project_id=project_id, actor_id=actor_id,
                       object_type="integration", object_id=integration_id,
                       detail={"projects": len(report.projects),
                               "itemTypes": len(report.item_types),
                               "limitations": report.limitations})
    return updated


async def approve_mapping(project_id: str, integration_id: str, *,
                          actor_id: str) -> Integration:
    integration = await integrations.require(integration_id, projectId=project_id)
    if not integration.capability_report:
        raise ConflictState("Run discovery before approving a mapping")
    if not integration.type_mappings:
        raise ValidationFailed("At least one canonical type mapping is required")
    updated = await integrations.update(integration_id, {
        "mappingApproved": True, "mappingApprovedBy": actor_id,
        "mappingApprovedAt": utcnow()}, projectId=project_id)
    await audit.record("integration.mapping_approved", project_id=project_id,
                       actor_id=actor_id, object_type="integration",
                       object_id=integration_id)
    return updated


async def publication_preview(project_id: str, integration_id: str,
                              approval_event_id: str,
                              item_ids: list[str] | None = None) -> PublicationPreview:
    integration = await integrations.require(integration_id, projectId=project_id)
    event = await approval_events.require(approval_event_id, projectId=project_id)
    if not event.committed or event.revoked or str(event.decision) != "approve":
        raise ConflictState("Only a committed, non revoked approval may be published")

    by_canonical = {t.canonical_type: t for t in integration.type_mappings}
    mappings = await external_mappings.list({"integrationId": integration_id})
    external_by_internal = {m.internal_id: m for m in mappings}

    rows: list[PublicationPreviewRow] = []
    blocked: list[dict[str, Any]] = []
    information_loss = False

    for entry in event.entries:
        if entry.reference_only:
            blocked.append({"itemId": entry.item_id, "stableId": entry.stable_id,
                            "reason": "Reference only: owned by another subtree"})
            continue
        if item_ids and entry.item_id not in item_ids:
            continue
        mapping = by_canonical.get(entry.item_type)
        if mapping is None or mapping.strategy == "unsupported":
            blocked.append({"itemId": entry.item_id, "stableId": entry.stable_id,
                            "reason": f"No mapping for canonical type {entry.item_type}"})
            information_loss = True
            continue

        payload = await _canonical_payload(project_id, entry.item_id, entry.item_type)
        unsupported_fields = [r.canonical_field for r in integration.field_rules
                              if (not r.supported or not r.external_field)
                              and r.canonical_field in payload
                              and r.direction != "inbound"]
        if unsupported_fields:
            information_loss = True
        existing = external_by_internal.get(entry.item_id)
        rows.append(PublicationPreviewRow(
            internal_id=entry.item_id, stable_id=entry.stable_id, title=entry.title,
            canonical_type=entry.item_type, external_type=mapping.external_type,
            action="update" if existing else "create",
            mapped_fields={r.canonical_field: payload.get(r.canonical_field)
                           for r in integration.field_rules
                           if r.supported and r.external_field
                           and r.direction != "inbound"},
            unsupported_fields=unsupported_fields,
            external_id=existing.external_id if existing else None,
            warnings=([f"{mapping.strategy} strategy: {mapping.note}"]
                      if mapping.note else []),
        ))

    hierarchy_note = None
    if integration.provider == Provider.ASANA:
        hierarchy_note = ("Asana has no native epic / feature / story hierarchy. The "
                          "canonical level travels as metadata and is reconstructed "
                          "internally.")
    elif integration.provider == Provider.JIRA:
        hierarchy_note = ("Jira has no guaranteed native level between epic and story. "
                          "The feature level uses the configured strategy.")

    return PublicationPreview(
        integration_id=integration_id, provider=str(integration.provider),
        approval_event_id=approval_event_id, rows=rows, blocked=blocked,
        hierarchy_note=hierarchy_note, information_loss=information_loss,
        total=len(rows))


async def _canonical_payload(project_id: str, item_id: str,
                             item_type: str) -> dict[str, Any]:
    item = await backlog_items.get(item_id, projectId=project_id)
    if not item:
        return {}
    version = await artifact_versions.get(item.current_version_id or "")
    estimate = await estimates.find_one({"projectId": project_id, "itemId": item_id,
                                         "superseded": False, "isRoughParent": False})
    criteria = ("\n".join(f"- {c.text}" for c in version.acceptance_criteria)
                if version else "")
    return {
        "id": item.id,
        "stableId": item.stable_id,
        "title": item.title,
        "description": version.description if version else None,
        "acceptanceCriteria": criteria,
        "priority": str(item.priority),
        "executionStatus": str(item.execution_status),
        "ownerId": item.owner_id,
        "storyPoints": estimate.story_points if estimate else None,
        "effortHours": total_hours(estimate) if estimate else None,
        "canonicalType": item_type,
        "originMarker": ORIGIN_MARKER,
    }


async def enqueue_publication(project_id: str, integration_id: str,
                              payload: PublishRequest, *, actor_id: str) -> OutboxJob:
    integration = await integrations.require(integration_id, projectId=project_id)
    if not integration.mapping_approved:
        raise ConflictState("The connector mapping must be approved before publication")
    if not integration.enabled:
        raise ConflictState("The connector is not enabled")

    event = await approval_events.require(payload.approval_event_id, projectId=project_id)
    if not event.committed or event.revoked:
        raise Forbidden("Only committed, non revoked approvals may be published")

    key = payload.idempotency_key or stable_hash(
        {"event": payload.approval_event_id, "integration": integration_id,
         "items": sorted(payload.item_ids)})
    existing = await outbox.find_one({"idempotencyKey": key})
    if existing:
        return existing

    job = OutboxJob(
        project_id=project_id, integration_id=integration_id, kind="publish",
        payload={"approvalEventId": payload.approval_event_id,
                 "itemIds": payload.item_ids, "dryRun": payload.dry_run},
        idempotency_key=key, available_at=utcnow(),
        approval_event_id=payload.approval_event_id,
    )
    await outbox.insert(job)
    await audit.record("integration.publication_enqueued", project_id=project_id,
                       actor_id=actor_id, object_type="outboxJob", object_id=job.id,
                       detail={"integrationId": integration_id,
                               "approvalEventId": payload.approval_event_id})
    return job


async def run_publication(job_id: str) -> OutboxJob:
    """Execute one outbox job. Per item outcomes are recorded individually."""
    job = await outbox.require(job_id)
    integration = await integrations.require(job.integration_id)
    adapter = await adapter_for(integration)
    preview = await publication_preview(job.project_id, job.integration_id,
                                        job.payload["approvalEventId"],
                                        job.payload.get("itemIds") or None)

    by_canonical = {t.canonical_type: t for t in integration.type_mappings}
    results: list[dict[str, Any]] = []
    failures = 0

    for row in preview.rows:
        if job.payload.get("dryRun"):
            results.append({"internalId": row.internal_id, "status": "dry_run",
                            "action": row.action})
            continue
        payload = await _canonical_payload(job.project_id, row.internal_id,
                                           row.canonical_type)
        mapping: TypeMapping = by_canonical[row.canonical_type]
        outcome = await adapter.publish(payload, type_mapping=mapping,
                                        field_rules=integration.field_rules,
                                        external_id=row.external_id)
        results.append({"internalId": row.internal_id, "status": outcome.status,
                        "externalId": outcome.external_id, "message": outcome.message,
                        "unsupportedFields": outcome.unsupported_fields})
        if outcome.status in ("created", "updated") and outcome.external_id:
            await _upsert_mapping(job.project_id, integration.id, row.internal_id,
                                  row.canonical_type, outcome, payload)
        elif outcome.status == "failed":
            failures += 1

    status = JobStatus.SUCCEEDED
    if failures and failures == len(preview.rows):
        status = JobStatus.FAILED
    elif failures:
        # A partial remote batch is never reported as a successful publication.
        status = JobStatus.PARTIAL

    updated = await outbox.update(job_id, {
        "status": str(status), "results": results, "attempts": job.attempts + 1,
        "lastError": None if status != JobStatus.FAILED else "All items failed",
    })
    if status in (JobStatus.SUCCEEDED, JobStatus.PARTIAL):
        await approval_events.raw_update(
            {"_id": job.payload["approvalEventId"]},
            {"$addToSet": {"publishedTargets": integration.id}})
    await integrations.update(integration.id, {
        "lastSyncAt": utcnow(),
        "health": "healthy" if status == JobStatus.SUCCEEDED else "degraded"})
    await audit.record("integration.published", project_id=job.project_id,
                       object_type="outboxJob", object_id=job_id,
                       detail={"status": str(status), "items": len(results),
                               "failures": failures})
    return updated


async def _upsert_mapping(project_id: str, integration_id: str, internal_id: str,
                          internal_type: str, outcome: Any,
                          payload: dict[str, Any]) -> None:
    existing = await external_mappings.find_one({"integrationId": integration_id,
                                                 "internalId": internal_id})
    common = {"title": payload.get("title"),
              "executionStatus": payload.get("executionStatus"),
              "storyPoints": payload.get("storyPoints"),
              "ownerId": payload.get("ownerId")}
    if existing:
        await external_mappings.update(existing.id, {
            "syncRevision": existing.sync_revision + 1,
            "lastPayloadHash": stable_hash(payload),
            "lastCommonValues": common, "lastSyncedAt": utcnow()})
        return
    await external_mappings.insert(ExternalMapping(
        project_id=project_id, integration_id=integration_id, internal_id=internal_id,
        internal_type=internal_type, external_id=outcome.external_id,
        external_key=outcome.external_key, external_url=outcome.url,
        sync_revision=1, last_payload_hash=stable_hash(payload),
        last_common_values=common, last_synced_at=utcnow()))


# --- inbound ---------------------------------------------------------------

STATUS_MAP = {
    "to do": ExecutionStatus.NOT_STARTED, "new": ExecutionStatus.NOT_STARTED,
    "ready": ExecutionStatus.READY, "approved": ExecutionStatus.READY,
    "in progress": ExecutionStatus.IN_PROGRESS, "active": ExecutionStatus.IN_PROGRESS,
    "doing": ExecutionStatus.IN_PROGRESS,
    "blocked": ExecutionStatus.BLOCKED,
    "in review": ExecutionStatus.IN_REVIEW, "review": ExecutionStatus.IN_REVIEW,
    "resolved": ExecutionStatus.IN_REVIEW,
    "done": ExecutionStatus.DONE, "closed": ExecutionStatus.DONE,
    "completed": ExecutionStatus.DONE, "removed": ExecutionStatus.CANCELLED,
}

#: Fields whose incoming change is operational and may apply immediately.
OPERATIONAL_FIELDS = {"executionStatus", "ownerId"}
#: Fields whose incoming change needs human review before it affects scope.
REVIEWABLE_FIELDS = {"title", "description", "acceptanceCriteria", "storyPoints",
                     "effortHours"}


async def ingest_remote_change(project_id: str, integration_id: str, *,
                               event_id: str, external_id: str,
                               fields: dict[str, Any],
                               origin: str | None = None) -> SyncEvent:
    """Apply one inbound change, deduplicated by provider event id."""
    if await sync_events.exists({"integrationId": integration_id, "eventId": event_id}):
        existing = await sync_events.find_one({"integrationId": integration_id,
                                               "eventId": event_id})
        return existing  # replay: nothing is applied twice

    event = SyncEvent(project_id=project_id, integration_id=integration_id,
                      event_id=event_id, direction="inbound", kind="item_update",
                      external_id=external_id, origin_marker=origin,
                      received_at=utcnow())

    if origin == ORIGIN_MARKER:
        event.status = "ignored"
        event.error = "Echo of a change this system published"
        await sync_events.insert(event)
        return event

    mapping = await external_mappings.find_one({"integrationId": integration_id,
                                                "externalId": external_id})
    if not mapping:
        event.status = "ignored"
        event.error = "No internal item is mapped to this external id"
        await sync_events.insert(event)
        return event

    event.internal_id = mapping.internal_id
    item = await backlog_items.get(mapping.internal_id, projectId=project_id)
    if not item:
        event.status = "failed"
        event.error = "The mapped internal item no longer exists"
        await sync_events.insert(event)
        return event

    incoming = _normalise_incoming(fields)
    current = await _canonical_payload(project_id, item.id, str(item.type))
    conflicts: list[ConflictField] = []
    applied: dict[str, Any] = {}

    for field, external_value in incoming.items():
        common = mapping.last_common_values.get(field)
        internal_value = current.get(field)
        internal_changed = internal_value != common
        external_changed = external_value != common
        if not external_changed:
            continue
        if internal_changed and internal_value != external_value:
            # Three way comparison; never a silent last write wins.
            conflicts.append(ConflictField(field=field, internal_value=internal_value,
                                           external_value=external_value,
                                           common_value=common))
            continue
        if field in OPERATIONAL_FIELDS:
            applied[field] = external_value
        elif field in REVIEWABLE_FIELDS:
            await _raise_change_request(project_id, item, field, external_value,
                                        internal_value, integration_id)

    if applied:
        changes: dict[str, Any] = {}
        if "executionStatus" in applied:
            changes["executionStatus"] = str(applied["executionStatus"])
        if "ownerId" in applied:
            changes["ownerId"] = applied["ownerId"]
        await backlog_items.update(item.id, changes, projectId=project_id)
        from app.models.planning import StatusEvent
        from app.repositories import status_events
        if "executionStatus" in applied:
            await status_events.insert(StatusEvent(
                project_id=project_id, item_id=item.id,
                from_status=str(item.execution_status),
                to_status=str(applied["executionStatus"]), at=utcnow(),
                origin=f"connector:{integration_id}"))

    event.status = "conflict" if conflicts else "applied"
    event.conflicts = conflicts
    event.payload_ref = {"fields": sorted(incoming)}
    await sync_events.insert(event)

    merged = dict(mapping.last_common_values)
    merged.update({k: v for k, v in incoming.items()
                   if not any(c.field == k for c in conflicts)})
    await external_mappings.update(mapping.id, {
        "lastCommonValues": merged, "syncRevision": mapping.sync_revision + 1,
        "lastSyncedAt": utcnow()})
    return event


def _normalise_incoming(fields: dict[str, Any]) -> dict[str, Any]:
    normalised: dict[str, Any] = {}
    status = (fields.get("status") or {}).get("name") if isinstance(
        fields.get("status"), dict) else fields.get("System.State") or fields.get("status")
    if isinstance(status, str):
        normalised["executionStatus"] = STATUS_MAP.get(status.lower(),
                                                       ExecutionStatus.IN_PROGRESS)
    if fields.get("completed") is True:
        normalised["executionStatus"] = ExecutionStatus.DONE
    assignee = fields.get("assignee") or fields.get("System.AssignedTo")
    if isinstance(assignee, dict):
        normalised["ownerId"] = assignee.get("accountId") or assignee.get("uniqueName") \
            or assignee.get("gid")
    elif isinstance(assignee, str):
        normalised["ownerId"] = assignee
    for source, target in (("summary", "title"), ("name", "title"),
                           ("System.Title", "title"),
                           ("description", "description"), ("notes", "description"),
                           ("System.Description", "description"),
                           ("Microsoft.VSTS.Scheduling.StoryPoints", "storyPoints")):
        if fields.get(source) is not None:
            normalised[target] = fields[source]
    return normalised


async def _raise_change_request(project_id: str, item: Any, field: str,
                                external_value: Any, internal_value: Any,
                                integration_id: str) -> ChangeRequest:
    index = await change_requests.count({"projectId": project_id}) + 1
    request = ChangeRequest(
        project_id=project_id, stable_id=f"CR-{index:03d}",
        title=f"External change to {field} on {item.stable_id}",
        reason=("A connector reported a change to content that is internally "
                "authoritative. It is recorded for review and does not inherit "
                "approval."),
        origin="connector", affected_item_ids=[item.id],
        evidence_refs=[{"integrationId": integration_id, "field": field,
                        "externalValue": external_value,
                        "internalValue": internal_value}],
    )
    await change_requests.insert(request)
    return request


async def resolve_conflict(project_id: str, sync_event_id: str,
                           resolutions: dict[str, str], *, actor_id: str) -> SyncEvent:
    event = await sync_events.require(sync_event_id, projectId=project_id)
    if not event.conflicts:
        raise ConflictState("This synchronisation event has no conflicts")
    item = await backlog_items.require(event.internal_id or "", projectId=project_id)
    applied: dict[str, Any] = {}
    for conflict in event.conflicts:
        choice = resolutions.get(conflict.field)
        if choice not in {"internal", "external"}:
            continue
        conflict.resolution = choice
        if choice == "external" and conflict.field in OPERATIONAL_FIELDS:
            applied[conflict.field] = conflict.external_value
    if applied:
        await backlog_items.update(item.id, {k: str(v) if k == "executionStatus" else v
                                             for k, v in applied.items()})
    updated = await sync_events.update(sync_event_id, {
        "status": "applied",
        "conflicts": [c.model_dump(by_alias=True) for c in event.conflicts]})
    await audit.record("integration.conflict_resolved", project_id=project_id,
                       actor_id=actor_id, object_type="syncEvent",
                       object_id=sync_event_id, detail={"resolutions": resolutions})
    return updated


async def sync_worklogs(project_id: str, integration_id: str,
                        entries: list[dict[str, Any]]) -> int:
    """Worklogs are identified by origin and external id to avoid duplicates."""
    integration = await integrations.require(integration_id, projectId=project_id)
    report = integration.capability_report
    if report and not report.supports_worklogs:
        raise ConflictState(f"{integration.provider} does not support worklog "
                            "synchronisation")
    created = 0
    for entry in entries:
        external_id = entry.get("externalId")
        if not external_id:
            continue
        if await worklogs.exists({"origin": f"connector:{integration_id}",
                                  "externalId": external_id}):
            continue
        mapping = await external_mappings.find_one({"integrationId": integration_id,
                                                    "externalId": entry.get("itemExternalId")})
        await worklogs.insert(Worklog(
            project_id=project_id, item_id=mapping.internal_id if mapping else None,
            user_id=entry.get("userId", "external"), role=entry.get("role"),
            work_date=entry["workDate"], hours=float(entry["hours"]),
            note=entry.get("note"), approved=False,
            origin=f"connector:{integration_id}", external_id=external_id))
        created += 1
    return created


async def schedule_reconciliation(project_id: str, integration_id: str) -> OutboxJob:
    job = OutboxJob(project_id=project_id, integration_id=integration_id,
                    kind="reconcile", payload={}, available_at=utcnow(),
                    idempotency_key=f"reconcile-{integration_id}-{new_id()[:8]}")
    await outbox.insert(job)
    return job


async def retry_with_backoff(job_id: str, error: str) -> OutboxJob:
    job = await outbox.require(job_id)
    attempts = job.attempts + 1
    if attempts >= job.max_attempts:
        return await outbox.update(job_id, {
            "status": str(JobStatus.FAILED), "attempts": attempts,
            "deadLettered": True, "lastError": error})
    delay = timedelta(seconds=min(300, 2 ** attempts * 5))
    return await outbox.update(job_id, {
        "status": str(JobStatus.QUEUED), "attempts": attempts,
        "availableAt": utcnow() + delay, "lastError": error})


async def health(project_id: str) -> list[dict[str, Any]]:
    rows = []
    for integration in await integrations.list({"projectId": project_id}):
        pending = await outbox.count({"integrationId": integration.id,
                                      "status": str(JobStatus.QUEUED)})
        dead = await outbox.count({"integrationId": integration.id, "deadLettered": True})
        conflicts = await sync_events.count({"integrationId": integration.id,
                                             "status": "conflict"})
        rows.append({
            "integrationId": integration.id, "provider": str(integration.provider),
            "name": integration.name, "enabled": integration.enabled,
            "mappingApproved": integration.mapping_approved,
            "health": integration.health, "lastSyncAt": integration.last_sync_at,
            "pendingJobs": pending, "deadLettered": dead, "openConflicts": conflicts,
            "isPrimary": integration.is_primary,
        })
    return rows
