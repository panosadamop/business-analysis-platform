"""Integration console endpoints (section 14)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Query, Request

from app.api.deps import ProjectContext, ProjectCtx, requires
from app.core.errors import Forbidden, NotFound
from app.core.policy import Permission
from app.models.integration import (ConflictResolution, Integration,
                                    IntegrationCreate, IntegrationUpdate,
                                    OutboxJob, PublicationPreview,
                                    PublishRequest, SyncEvent)
from app.repositories import external_mappings, integrations, outbox, sync_events
from app.services import integrations as service
from app.workers import queue

router = APIRouter(tags=["integrations"], prefix="/projects/{project_id}")


@router.get("/integrations", response_model=list[Integration])
async def list_integrations(project_id: str,
                            ctx: ProjectContext = requires(Permission.INTEGRATION_MANAGE)
                            ) -> list[Integration]:
    return await integrations.list({"projectId": project_id})


@router.post("/integrations", response_model=Integration, status_code=201)
async def create_integration(project_id: str, payload: IntegrationCreate,
                             ctx: ProjectContext = requires(Permission.INTEGRATION_MANAGE)
                             ) -> Integration:
    return await service.create(project_id, payload, actor_id=ctx.user.id)


@router.patch("/integrations/{integration_id}", response_model=Integration)
async def update_integration(project_id: str, integration_id: str,
                             payload: IntegrationUpdate,
                             ctx: ProjectContext = requires(Permission.INTEGRATION_MANAGE)
                             ) -> Integration:
    return await service.update(project_id, integration_id, payload, actor_id=ctx.user.id)


@router.post("/integrations/{integration_id}/discover", response_model=Integration)
async def discover(project_id: str, integration_id: str,
                   ctx: ProjectContext = requires(Permission.INTEGRATION_MANAGE)
                   ) -> Integration:
    """Capability discovery. A compatibility report precedes any mapping."""
    return await service.discover(project_id, integration_id, actor_id=ctx.user.id)


@router.post("/integrations/{integration_id}/approve-mapping", response_model=Integration)
async def approve_mapping(project_id: str, integration_id: str,
                          ctx: ProjectContext = requires(Permission.INTEGRATION_MANAGE)
                          ) -> Integration:
    return await service.approve_mapping(project_id, integration_id, actor_id=ctx.user.id)


@router.get("/integrations/{integration_id}/preview", response_model=PublicationPreview)
async def preview(project_id: str, integration_id: str, approval_event_id: str = Query(...),
                  ctx: ProjectContext = requires(Permission.INTEGRATION_PUBLISH)
                  ) -> PublicationPreview:
    """Shows mapped fields, unsupported fields and anything that would be lost."""
    return await service.publication_preview(project_id, integration_id,
                                             approval_event_id)


@router.post("/integrations/{integration_id}/publish", response_model=OutboxJob,
             status_code=202)
async def publish(project_id: str, integration_id: str, payload: PublishRequest,
                  idempotency_key: str | None = Header(None),
                  ctx: ProjectContext = requires(Permission.INTEGRATION_PUBLISH)
                  ) -> OutboxJob:
    if idempotency_key and not payload.idempotency_key:
        payload.idempotency_key = idempotency_key
    job = await service.enqueue_publication(project_id, integration_id, payload,
                                            actor_id=ctx.user.id)
    await queue.enqueue("publish", {"outboxJobId": job.id}, project_id=project_id,
                        idempotency_key=f"outbox-{job.id}", requested_by=ctx.user.id)
    return job


@router.get("/integrations/{integration_id}/jobs", response_model=list[OutboxJob])
async def list_jobs(project_id: str, integration_id: str,
                    ctx: ProjectContext = requires(Permission.INTEGRATION_MANAGE)
                    ) -> list[OutboxJob]:
    return await outbox.list({"projectId": project_id, "integrationId": integration_id},
                             sort=[("createdAt", -1)], limit=100)


@router.get("/integrations/{integration_id}/conflicts", response_model=list[SyncEvent])
async def list_conflicts(project_id: str, integration_id: str,
                         ctx: ProjectContext = requires(Permission.INTEGRATION_MANAGE)
                         ) -> list[SyncEvent]:
    return await sync_events.list({"projectId": project_id,
                                   "integrationId": integration_id,
                                   "status": "conflict"}, sort=[("createdAt", -1)])


@router.post("/integrations/conflicts/resolve", response_model=SyncEvent)
async def resolve_conflict(project_id: str, payload: ConflictResolution,
                           ctx: ProjectContext = requires(Permission.INTEGRATION_MANAGE)
                           ) -> SyncEvent:
    return await service.resolve_conflict(project_id, payload.sync_event_id,
                                          payload.resolutions, actor_id=ctx.user.id)


@router.post("/integrations/{integration_id}/sync", status_code=202)
async def trigger_sync(project_id: str, integration_id: str,
                       ctx: ProjectContext = requires(Permission.INTEGRATION_MANAGE)
                       ) -> dict[str, Any]:
    job = await queue.enqueue("sync", {"integrationId": integration_id},
                              project_id=project_id, requested_by=ctx.user.id)
    return {"jobId": job.id, "status": str(job.status)}


@router.get("/integrations/{integration_id}/mappings")
async def list_mappings(project_id: str, integration_id: str,
                        ctx: ProjectContext = requires(Permission.INTEGRATION_MANAGE)
                        ) -> list[dict[str, Any]]:
    rows = await external_mappings.list({"integrationId": integration_id}, limit=2000)
    return [r.model_dump(by_alias=True) for r in rows]


@router.get("/integrations-health")
async def health(project_id: str, ctx: ProjectCtx) -> list[dict[str, Any]]:
    ctx.require(Permission.METRICS_READ)
    return await service.health(project_id)


webhooks = APIRouter(tags=["integrations"])


@webhooks.post("/webhooks/{provider}/{integration_id}")
async def receive_webhook(provider: str, integration_id: str, request: Request
                          ) -> dict[str, Any]:
    """Webhook receiver.

    Authenticity is verified with the provider's supported mechanism. An
    unverified payload is rejected rather than trusted, and a replayed event id
    is ignored instead of applied twice.
    """
    integration = await integrations.get(integration_id)
    if not integration or str(integration.provider) != provider:
        raise NotFound("Unknown webhook destination")
    body = await request.body()
    adapter = await service.adapter_for(integration)
    if not adapter.verify_webhook(dict(request.headers), body):
        raise Forbidden("Webhook signature verification failed")

    payload = await request.json()
    events = payload.get("events") or [payload]
    results = []
    for event in events:
        event_id = str(event.get("id") or event.get("eventId") or event.get("timestamp"))
        external_id = str(event.get("resource", {}).get("id")
                          or event.get("issue", {}).get("id")
                          or event.get("gid") or "")
        fields = (event.get("issue", {}).get("fields")
                  or event.get("resource", {}).get("fields") or event.get("fields") or {})
        result = await service.ingest_remote_change(
            integration.project_id, integration.id, event_id=event_id,
            external_id=external_id, fields=fields,
            origin=event.get("originMarker"))
        results.append({"eventId": event_id, "status": result.status})
    return {"received": len(results), "results": results}
