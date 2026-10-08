"""Durable job queue backed by MongoDB (NFR-05).

Long running work is queued, observable and restartable. Claiming uses an
atomic find-and-modify so two workers never run the same job, and an
idempotency key makes a re-submission return the existing job rather than
duplicating approved artifacts or remote items.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from pymongo import ReturnDocument

from app.core.utils import utcnow
from app.db.mongo import C, col
from app.models.collaboration import JobRecord
from app.models.common import JobStatus
from app.repositories import jobs as jobs_repo


async def enqueue(kind: str, payload: dict[str, Any], *, project_id: str | None = None,
                  idempotency_key: str | None = None, requested_by: str | None = None,
                  correlation_id: str | None = None,
                  delay_seconds: float = 0) -> JobRecord:
    if idempotency_key:
        existing = await jobs_repo.find_one({"idempotencyKey": idempotency_key})
        if existing:
            return existing
    job = JobRecord(
        project_id=project_id, kind=kind, payload=payload,
        available_at=utcnow() + timedelta(seconds=delay_seconds),
        idempotency_key=idempotency_key, requested_by=requested_by,
        correlation_id=correlation_id,
    )
    await jobs_repo.insert(job)
    return job


async def claim() -> JobRecord | None:
    doc = await col(C.JOBS).find_one_and_update(
        {"status": str(JobStatus.QUEUED), "availableAt": {"$lte": utcnow()}},
        {"$set": {"status": str(JobStatus.RUNNING), "startedAt": utcnow()},
         "$inc": {"attempts": 1}},
        sort=[("createdAt", 1)],
        return_document=ReturnDocument.AFTER)
    if not doc:
        return None
    doc["id"] = doc.pop("_id")
    return JobRecord(**doc)


async def complete(job_id: str, *, result: dict[str, Any] | None = None,
                   message: str | None = None) -> None:
    await jobs_repo.update(job_id, {"status": str(JobStatus.SUCCEEDED),
                                    "finishedAt": utcnow(), "progress": 1.0,
                                    "result": result or {}, "message": message})


async def fail(job_id: str, error: str, *, retry: bool = True) -> None:
    job = await jobs_repo.require(job_id)
    if retry and job.attempts < job.max_attempts:
        delay = timedelta(seconds=min(300, 2 ** job.attempts * 5))
        await jobs_repo.update(job_id, {"status": str(JobStatus.QUEUED),
                                        "availableAt": utcnow() + delay,
                                        "error": error})
        return
    await jobs_repo.update(job_id, {"status": str(JobStatus.FAILED),
                                    "finishedAt": utcnow(), "error": error})


async def progress(job_id: str, value: float, message: str | None = None) -> None:
    await jobs_repo.update(job_id, {"progress": round(value, 2), "message": message})


async def cancel(job_id: str) -> JobRecord:
    return await jobs_repo.update(job_id, {"cancelRequested": True})


async def requeue_stale(older_than_minutes: int = 30) -> int:
    """Recover jobs whose worker died mid run so nothing is silently lost."""
    cutoff = utcnow() - timedelta(minutes=older_than_minutes)
    return await jobs_repo.raw_update(
        {"status": str(JobStatus.RUNNING), "startedAt": {"$lt": cutoff}},
        {"$set": {"status": str(JobStatus.QUEUED), "availableAt": utcnow()}})
