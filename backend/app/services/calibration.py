"""Historical calibration of estimates (section 11.4).

Transparent, rule based ratios and similarity retrieval come first. A cohort
adjustment needs at least the configured minimum of usable completed stories;
below that the system reports insufficient evidence and keeps using templates.
Candidates are evaluated on a time separated holdout and require administrator
approval before activation. Old estimates are never overwritten, and story
points are never treated as actual time.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.config import settings
from app.core.errors import ConflictState, NotFound
from app.core.utils import new_id, utcnow
from app.db.mongo import C, col
from app.models.common import Base
from app.repositories import (backlog_items, estimates, projects, status_events,
                              worklogs)
from app.services import audit
from app.services.estimation import total_hours


class CalibrationVersion(Base):
    id: str
    status: str  # candidate | active | rejected | rolled_back
    created_at: datetime
    created_by: str | None = None
    cohort_size: int = 0
    usable_size: int = 0
    method: str = "ratio"
    ratios: dict[str, float] = {}
    evaluation: dict[str, Any] = {}
    sufficient: bool = False
    activated_at: datetime | None = None
    activated_by: str | None = None
    note: str | None = None
    project_opt_out: list[str] = []


@dataclass
class CohortRow:
    item_id: str
    project_id: str
    estimated_hours: float
    actual_hours: float
    story_points: float | None
    completed_at: datetime
    role_mix: dict[str, float]
    labels: list[str]
    rework: bool
    scope_changed: bool


async def collect_cohort(project_ids: list[str] | None = None) -> list[CohortRow]:
    """Completed stories with complete, approved actual time only."""
    query: dict[str, Any] = {"type": "story", "executionStatus": "done"}
    if project_ids:
        query["projectId"] = {"$in": project_ids}
    items = await backlog_items.list(query, limit=20000)
    if not items:
        return []
    item_ids = [i.id for i in items]

    estimate_rows = await estimates.list({"itemId": {"$in": item_ids},
                                          "superseded": False, "isRoughParent": False})
    estimate_by_item = {e.item_id: e for e in estimate_rows}
    log_rows = await worklogs.aggregate([
        {"$match": {"itemId": {"$in": item_ids}, "approved": True}},
        {"$group": {"_id": "$itemId", "hours": {"$sum": "$hours"}}},
    ])
    actual_by_item = {r["_id"]: r["hours"] for r in log_rows}
    done_events = await status_events.list({"itemId": {"$in": item_ids},
                                            "toStatus": "done"}, sort=[("at", 1)])
    done_at = {e.item_id: e.at for e in done_events}

    cohort: list[CohortRow] = []
    for item in items:
        estimate = estimate_by_item.get(item.id)
        actual = actual_by_item.get(item.id)
        if not estimate or not actual:
            # Missing timesheet data excludes the row rather than biasing it.
            continue
        estimated = total_hours(estimate)
        if estimated <= 0 or actual <= 0:
            continue
        cohort.append(CohortRow(
            item_id=item.id, project_id=item.project_id, estimated_hours=estimated,
            actual_hours=round(actual, 2), story_points=estimate.story_points,
            completed_at=done_at.get(item.id, item.updated_at),
            role_mix={r.role: r.hours for r in estimate.role_efforts},
            labels=item.labels, rework=False,
            scope_changed=item.requires_reapproval,
        ))
    return cohort


def _metrics(rows: list[CohortRow], ratio: float) -> dict[str, Any]:
    """Error metrics suitable for positive effort values."""
    if not rows:
        return {"n": 0}
    errors = []
    log_errors = []
    within = 0
    for row in rows:
        predicted = row.estimated_hours * ratio
        errors.append(abs(predicted - row.actual_hours) / row.actual_hours)
        log_errors.append(abs((predicted / row.actual_hours) ** 1))
        if 0.5 * row.actual_hours <= predicted <= 1.5 * row.actual_hours:
            within += 1
    return {
        "n": len(rows),
        "mape": round(statistics.fmean(errors) * 100, 2),
        "medianAbsolutePercentageError": round(statistics.median(errors) * 100, 2),
        "meanRatio": round(statistics.fmean(log_errors), 3),
        "intervalCoverage50to150Percent": round(within / len(rows) * 100, 1),
    }


async def build_candidate(*, actor_id: str, project_ids: list[str] | None = None,
                          note: str | None = None) -> CalibrationVersion:
    cohort = await collect_cohort(project_ids)
    minimum = settings.calibration_min_cohort
    usable = [r for r in cohort if not r.scope_changed]

    version = CalibrationVersion(
        id=f"calib-{new_id()[:12]}", status="candidate", created_at=utcnow(),
        created_by=actor_id, cohort_size=len(cohort), usable_size=len(usable),
        note=note,
    )

    if len(usable) < minimum:
        version.sufficient = False
        version.evaluation = {
            "insufficientEvidence": True,
            "required": minimum,
            "available": len(usable),
            "message": (f"Only {len(usable)} usable completed stories are available; "
                        f"{minimum} are required. Template estimates remain in use and "
                        "no learned accuracy is claimed."),
            "excludedForMissingTimesheets": len(cohort) - len(usable),
        }
        await col(C.CALIBRATION_VERSIONS).insert_one(
            {**version.model_dump(by_alias=True), "_id": version.id})
        return version

    # Time separated holdout: the most recent 25 percent is never trained on.
    ordered = sorted(usable, key=lambda r: r.completed_at)
    split = int(len(ordered) * 0.75)
    train, holdout = ordered[:split], ordered[split:]

    overall = statistics.fmean(r.actual_hours / r.estimated_hours for r in train)
    ratios: dict[str, float] = {"overall": round(overall, 3)}
    by_label: dict[str, list[float]] = {}
    for row in train:
        for label in row.labels or ["unlabelled"]:
            by_label.setdefault(label, []).append(row.actual_hours / row.estimated_hours)
    for label, values in by_label.items():
        if len(values) >= 10:
            ratios[label] = round(statistics.fmean(values), 3)

    version.ratios = ratios
    version.sufficient = True
    version.evaluation = {
        "train": _metrics(train, overall),
        "holdout": _metrics(holdout, overall),
        "baselineHoldout": _metrics(holdout, 1.0),
        "method": "mean actual to estimate ratio, evaluated on a time separated holdout",
        "note": ("Improvement is an objective to measure, not a guaranteed outcome. "
                 "Story points are never used as actual time."),
    }
    candidate_error = version.evaluation["holdout"].get("mape", 1e9)
    baseline_error = version.evaluation["baselineHoldout"].get("mape", 0)
    version.evaluation["improvesOnBaseline"] = candidate_error < baseline_error

    await col(C.CALIBRATION_VERSIONS).insert_one(
        {**version.model_dump(by_alias=True), "_id": version.id})
    await audit.record("calibration.candidate_built", actor_id=actor_id,
                       object_type="calibrationVersion", object_id=version.id,
                       detail={"cohort": len(cohort), "usable": len(usable),
                               "sufficient": version.sufficient})
    return version


async def activate(version_id: str, *, actor_id: str) -> CalibrationVersion:
    doc = await col(C.CALIBRATION_VERSIONS).find_one({"_id": version_id})
    if not doc:
        raise NotFound("Calibration version not found")
    version = CalibrationVersion(**{**doc, "id": doc["_id"]})
    if not version.sufficient:
        raise ConflictState("A candidate without sufficient evidence cannot be activated")
    if not version.evaluation.get("improvesOnBaseline", False):
        raise ConflictState(
            "The candidate did not improve on the current method in holdout "
            "evaluation. It stays inactive and the previous method remains available.",
            details={"evaluation": version.evaluation})

    await col(C.CALIBRATION_VERSIONS).update_many(
        {"status": "active"}, {"$set": {"status": "rolled_back"}})
    await col(C.CALIBRATION_VERSIONS).update_one(
        {"_id": version_id},
        {"$set": {"status": "active", "activatedAt": utcnow(), "activatedBy": actor_id}})
    await audit.record("calibration.activated", actor_id=actor_id,
                       object_type="calibrationVersion", object_id=version_id,
                       detail={"ratios": version.ratios})
    version.status = "active"
    version.activated_at = utcnow()
    version.activated_by = actor_id
    return version


async def rollback(version_id: str, *, actor_id: str) -> None:
    await col(C.CALIBRATION_VERSIONS).update_one(
        {"_id": version_id}, {"$set": {"status": "rolled_back"}})
    await audit.record("calibration.rolled_back", actor_id=actor_id,
                       object_type="calibrationVersion", object_id=version_id)


async def active_version() -> CalibrationVersion | None:
    doc = await col(C.CALIBRATION_VERSIONS).find_one({"status": "active"})
    return CalibrationVersion(**{**doc, "id": doc["_id"]}) if doc else None


async def list_versions(limit: int = 50) -> list[CalibrationVersion]:
    cursor = col(C.CALIBRATION_VERSIONS).find().sort("createdAt", -1).limit(limit)
    return [CalibrationVersion(**{**doc, "id": doc["_id"]})
            for doc in await cursor.to_list(length=limit)]


async def suggest_adjustment(project_id: str, estimated_hours: float,
                             labels: list[str] | None = None) -> dict[str, Any]:
    """Apply the active calibration, honouring the project opt out."""
    project = await projects.require(project_id)
    version = await active_version()
    if not version:
        return {"adjustedHours": estimated_hours, "applied": False,
                "reason": "No calibration is active; template estimates are used."}
    if project.id in version.project_opt_out:
        return {"adjustedHours": estimated_hours, "applied": False,
                "reason": "This project has opted out of calibration."}
    ratio = next((version.ratios[label] for label in (labels or [])
                  if label in version.ratios), version.ratios.get("overall", 1.0))
    return {
        "adjustedHours": round(estimated_hours * ratio, 2),
        "applied": True,
        "ratio": ratio,
        "calibrationVersionId": version.id,
        "cohortSize": version.usable_size,
        "evaluation": version.evaluation.get("holdout"),
        "reason": "Adjusted by the active calibration ratio; the original estimate is kept.",
    }
