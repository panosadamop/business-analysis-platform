"""Background worker process.

Runs ingestion, AI analysis, exports, connector synchronisation and scheduled
maintenance. Start with ``python -m app.workers.worker``.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.core.config import settings
from app.core.policy import Permission
from app.core.utils import utcnow
from app.db.mongo import close, ensure_indexes
from app.models.collaboration import ExportRequest, JobRecord
from app.models.common import JobStatus
from app.repositories import integrations, outbox, projects
from app.workers import queue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s correlation=%(correlation_id)s %(message)s"
    if False else "%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("worker")

#: Touched on every scheduler tick so the container health probe can tell a live
#: worker from a hung one.
HEARTBEAT = Path(os.environ.get("APP_WORKER_HEARTBEAT", "/app/var/worker-heartbeat"))


def beat() -> None:
    try:
        HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT.write_text(str(time.time()))
    except OSError:  # pragma: no cover - a read only volume is not fatal
        pass

_stopping = False


async def handle_analysis(job: JobRecord) -> dict[str, Any]:
    from app.ai import orchestrator

    analysis = await orchestrator.run_job(job.payload["analysisJobId"])
    return {"analysisJobId": analysis.id, "status": str(analysis.status),
            "counts": analysis.created_counts}


async def handle_export(job: JobRecord) -> dict[str, Any]:
    from app.services import exports

    project = await projects.require(job.payload["projectId"])
    request = ExportRequest(**job.payload["request"])
    permissions = {Permission(p) for p in job.payload.get("permissions", [])}
    result = await exports.run_export(project, request, permissions=permissions,
                                      is_client=job.payload.get("isClient", False),
                                      actor_id=job.requested_by or "system")
    return {"exportJobId": result.id, "objectKey": result.object_key,
            "rowCounts": result.row_counts, "warnings": result.warnings}


async def handle_publish(job: JobRecord) -> dict[str, Any]:
    from app.services import integrations as integration_service

    try:
        result = await integration_service.run_publication(job.payload["outboxJobId"])
    except Exception as exc:
        await integration_service.retry_with_backoff(job.payload["outboxJobId"], str(exc))
        raise
    return {"outboxJobId": result.id, "status": str(result.status),
            "results": result.results}


async def handle_sync(job: JobRecord) -> dict[str, Any]:
    """Poll a connector for remote changes (company hosted deployments)."""
    from app.services import integrations as integration_service

    integration = await integrations.require(job.payload["integrationId"])
    adapter = await integration_service.adapter_for(integration)
    since = integration.last_sync_at.isoformat() if integration.last_sync_at else None
    applied = conflicts = 0
    for remote in await adapter.fetch_changes(since):
        event = await integration_service.ingest_remote_change(
            integration.project_id, integration.id,
            event_id=f"poll:{remote.external_id}:{remote.revision}",
            external_id=remote.external_id, fields=remote.fields)
        if event.status == "applied":
            applied += 1
        elif event.status == "conflict":
            conflicts += 1
    await integrations.update(integration.id, {"lastSyncAt": utcnow()})
    return {"applied": applied, "conflicts": conflicts}


async def handle_snapshot(job: JobRecord) -> dict[str, Any]:
    from app.services import metrics

    taken = 0
    for project in await projects.list({"archived": False}):
        await metrics.snapshot_daily(project)
        taken += 1
    return {"projects": taken}


async def handle_outbox_scan(_: JobRecord) -> dict[str, Any]:
    """Promote due outbox jobs into the worker queue."""
    due = await outbox.list({"status": str(JobStatus.QUEUED),
                             "availableAt": {"$lte": utcnow()}}, limit=50)
    for entry in due:
        await outbox.update(entry.id, {"status": str(JobStatus.RUNNING)})
        await queue.enqueue("publish" if entry.kind == "publish" else "reconcile",
                            {"outboxJobId": entry.id}, project_id=entry.project_id,
                            idempotency_key=f"outbox-{entry.id}")
    return {"promoted": len(due)}


async def handle_reconcile(job: JobRecord) -> dict[str, Any]:
    entry = await outbox.require(job.payload["outboxJobId"])
    await outbox.update(entry.id, {"status": str(JobStatus.SUCCEEDED),
                                   "results": [{"note": "Reconciliation task recorded. "
                                                        "Published items are never deleted "
                                                        "automatically."}]})
    return {"outboxJobId": entry.id}


HANDLERS: dict[str, Callable[[JobRecord], Awaitable[dict[str, Any]]]] = {
    "analysis": handle_analysis,
    "export": handle_export,
    "publish": handle_publish,
    "sync": handle_sync,
    "snapshot": handle_snapshot,
    "outbox_scan": handle_outbox_scan,
    "reconcile": handle_reconcile,
}


async def run_once() -> bool:
    job = await queue.claim()
    if job is None:
        return False
    handler = HANDLERS.get(job.kind)
    if handler is None:
        await queue.fail(job.id, f"No handler registered for '{job.kind}'", retry=False)
        return True
    log.info("running job %s kind=%s project=%s", job.id, job.kind, job.project_id)
    try:
        result = await handler(job)
        await queue.complete(job.id, result=result)
        log.info("job %s finished", job.id)
    except Exception as exc:
        log.exception("job %s failed", job.id)
        await queue.fail(job.id, str(exc))
    return True


async def scheduler() -> None:
    """Periodic maintenance: outbox scan, stale recovery and daily snapshots."""
    while not _stopping:
        try:
            beat()
            await queue.requeue_stale()
            await queue.enqueue("outbox_scan", {},
                                idempotency_key=f"outbox-scan-{utcnow():%Y%m%d%H%M}")
            if utcnow().hour == 1:
                await queue.enqueue("snapshot", {},
                                    idempotency_key=f"snapshot-{utcnow():%Y%m%d}")
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(60)


async def main() -> None:
    await ensure_indexes()
    beat()
    log.info("worker started with concurrency=%s", settings.worker_concurrency)

    async def loop(index: int) -> None:
        while not _stopping:
            worked = await run_once()
            if not worked:
                await asyncio.sleep(settings.worker_poll_seconds)

    tasks = [asyncio.create_task(loop(i)) for i in range(settings.worker_concurrency)]
    tasks.append(asyncio.create_task(scheduler()))
    await asyncio.gather(*tasks, return_exceptions=True)
    await close()


def _stop(*_: Any) -> None:
    global _stopping
    _stopping = True
    log.info("worker stopping")


if __name__ == "__main__":
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _stop)
        except (ValueError, AttributeError):  # pragma: no cover - Windows
            pass
    asyncio.run(main())
