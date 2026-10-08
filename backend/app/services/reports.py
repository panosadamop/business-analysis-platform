"""Report builder datasets (section 16).

Report queries use a validated allowlist of datasets, fields and filters. No
client supplied query fragment ever reaches the database. Column level
restrictions, including fields derived from hidden costs, are applied server
side, and a saved template can never grant a permission its reader lacks.
"""
from __future__ import annotations

from typing import Any, Callable, Awaitable

from app.core.errors import Forbidden, ValidationFailed
from app.core.policy import CLIENT_FORBIDDEN_FIELDS, Permission
from app.core.utils import new_id, utcnow
from app.models.collaboration import ReportDataset, ReportPreview
from app.models.project import Project
from app.repositories import (approval_events, artifact_versions, backlog_items,
                              change_requests, estimates, evidence_links,
                              iterations, questions, status_events, test_cases,
                              worklogs)
from app.services import integrations as integration_service
from app.services import metrics
from app.services.estimation import (effective_rate_card, estimate_cost,
                                     role_breakdown, total_hours)


class Column:
    def __init__(self, key: str, label: str, type_: str = "string", *,
                 requires: Permission | None = None, client_safe: bool = True) -> None:
        self.key = key
        self.label = label
        self.type = type_
        self.requires = requires
        self.client_safe = client_safe

    def describe(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "type": self.type,
                "clientSafe": self.client_safe,
                "requires": str(self.requires) if self.requires else None}


COLUMNS: dict[str, list[Column]] = {
    ReportDataset.BACKLOG: [
        Column("stableId", "ID"), Column("type", "Type"), Column("title", "Title"),
        Column("parentStableId", "Parent"), Column("state", "Approval state"),
        Column("executionStatus", "Execution status"), Column("priority", "Priority"),
        Column("version", "Version", "number"),
        Column("approvedVersion", "Approved version", "number"),
        Column("storyPoints", "Story points", "number"),
        Column("effortHours", "Effort (person hours)", "number"),
        Column("effortDays", "Effort (person days)", "number"),
        Column("estimatedCost", "Estimated cost", "money",
               requires=Permission.COST_READ, client_safe=False),
        Column("criteriaCount", "Acceptance criteria", "number"),
        Column("testCount", "Linked tests", "number"),
        Column("ownerId", "Owner"),
    ],
    ReportDataset.ESTIMATES_BY_ROLE: [
        Column("stableId", "ID"), Column("title", "Title"), Column("role", "Role"),
        Column("hours", "Person hours", "number"),
        Column("lowHours", "Low", "number"), Column("highHours", "High", "number"),
        Column("method", "Method"), Column("confidenceLabel", "Confidence"),
        Column("rate", "Hourly rate", "money", requires=Permission.RATE_READ,
               client_safe=False),
        Column("cost", "Cost", "money", requires=Permission.COST_READ, client_safe=False),
    ],
    ReportDataset.PLANNED_VS_ACTUAL: [
        Column("stableId", "ID"), Column("title", "Title"),
        Column("plannedHours", "Planned", "number"),
        Column("actualHours", "Actual", "number"),
        Column("remainingHours", "Remaining", "number"),
        Column("executionStatus", "Execution status"),
    ],
    ReportDataset.COST_FORECAST: [
        Column("category", "Category"),
        Column("amount", "Amount", "money", requires=Permission.COST_READ,
               client_safe=False),
        Column("currency", "Currency", requires=Permission.COST_READ, client_safe=False),
        Column("note", "Note"),
    ],
    ReportDataset.CAPACITY: [
        Column("displayName", "Person"), Column("role", "Role"),
        Column("periodStart", "From", "date"), Column("periodEnd", "To", "date"),
        Column("scheduledHours", "Scheduled", "number"),
        Column("leaveHours", "Leave", "number"),
        Column("allocationPercent", "Allocation %", "number"),
        Column("focusFactor", "Focus factor", "number"),
        Column("availableHours", "Available", "number"),
    ],
    ReportDataset.SPRINT_PROGRESS: [
        Column("name", "Sprint"), Column("state", "State"),
        Column("startDate", "Start", "date"), Column("endDate", "End", "date"),
        Column("capacityHours", "Capacity", "number"),
        Column("committedPoints", "Committed points", "number"),
        Column("completedPoints", "Completed points", "number"),
        Column("itemCount", "Items", "number"),
        Column("doneCount", "Done", "number"),
    ],
    ReportDataset.KANBAN_FLOW: [
        Column("stableId", "ID"), Column("title", "Title"),
        Column("column", "Column"), Column("enteredAt", "Entered", "datetime"),
        Column("ageDays", "Age (days)", "number"),
        Column("blockedReason", "Blocked reason"),
        Column("serviceClass", "Service class"),
    ],
    ReportDataset.TRACEABILITY: [
        Column("sourceTitle", "Evidence"), Column("locator", "Locator"),
        Column("targetType", "Target type"), Column("targetStableId", "Target"),
        Column("targetTitle", "Target title"), Column("linkType", "Link"),
    ],
    ReportDataset.TESTBOOK: [
        Column("stableId", "Test ID"), Column("title", "Title"),
        Column("storyStableId", "Story"), Column("criterionIds", "Criteria"),
        Column("testType", "Type"), Column("priority", "Priority"),
        Column("state", "State"), Column("reviewState", "Review state"),
        Column("hasGherkin", "Gherkin", "boolean"),
    ],
    ReportDataset.APPROVAL_HISTORY: [
        Column("decidedAt", "Decided at", "datetime"), Column("decision", "Decision"),
        Column("rootStableId", "Root"), Column("rootType", "Root type"),
        Column("entries", "Items in bundle", "number"),
        Column("inherited", "Inherited", "number"),
        Column("waivers", "Waivers", "number"),
        Column("decidedBy", "Approver"), Column("revoked", "Revoked", "boolean"),
    ],
    ReportDataset.CHANGE_IMPACT: [
        Column("stableId", "Change"), Column("title", "Title"),
        Column("status", "Status"), Column("origin", "Origin"),
        Column("affectedItems", "Affected items", "number"),
        Column("effortDeltaHours", "Effort delta", "number"),
        Column("dateImpactDays", "Date impact (days)", "number"),
        Column("costDelta", "Cost delta", "money", requires=Permission.COST_READ,
               client_safe=False),
    ],
    ReportDataset.CONNECTOR_HEALTH: [
        Column("provider", "Provider"), Column("name", "Connector"),
        Column("enabled", "Enabled", "boolean"),
        Column("mappingApproved", "Mapping approved", "boolean"),
        Column("health", "Health"), Column("pendingJobs", "Pending jobs", "number"),
        Column("deadLettered", "Dead lettered", "number"),
        Column("openConflicts", "Open conflicts", "number"),
        Column("lastSyncAt", "Last sync", "datetime"),
    ],
    ReportDataset.QUESTIONS: [
        Column("stableId", "ID"), Column("title", "Question"),
        Column("severity", "Severity"), Column("kind", "Kind"),
        Column("status", "Status"), Column("ownerId", "Owner"),
        Column("answer", "Answer"),
    ],
}

ALLOWED_FILTERS = {
    "approvalState", "executionStatus", "type", "priority", "iterationId",
    "ownerId", "severity", "status", "release", "team", "from", "to", "rootId",
}


def allowed_columns(dataset: str, *, permissions: set[Permission],
                    is_client: bool) -> list[Column]:
    columns = COLUMNS.get(dataset)
    if columns is None:
        raise ValidationFailed(f"Unknown dataset '{dataset}'")
    visible: list[Column] = []
    for column in columns:
        if is_client and (not column.client_safe
                          or column.key in CLIENT_FORBIDDEN_FIELDS):
            continue
        if column.requires and column.requires not in permissions:
            continue
        visible.append(column)
    return visible


def validate_filters(filters: dict[str, Any]) -> dict[str, Any]:
    unknown = set(filters) - ALLOWED_FILTERS
    if unknown:
        raise ValidationFailed("Unsupported report filter",
                               details={"unknown": sorted(unknown)})
    return filters


async def build(project: Project, dataset: str, *, filters: dict[str, Any],
                fields: list[str], permissions: set[Permission], is_client: bool,
                limit: int = 5000) -> ReportPreview:
    validate_filters(filters)
    columns = allowed_columns(dataset, permissions=permissions, is_client=is_client)
    if fields:
        requested = set(fields)
        unknown = requested - {c.key for c in COLUMNS[dataset]}
        if unknown:
            raise ValidationFailed("Unknown report field",
                                   details={"unknown": sorted(unknown)})
        denied = requested - {c.key for c in columns}
        if denied:
            # A saved template cannot grant additional permissions.
            raise Forbidden("The report requests fields you are not permitted to read",
                            details={"denied": sorted(denied)})
        columns = [c for c in columns if c.key in requested]

    builder = BUILDERS.get(dataset)
    if builder is None:
        raise ValidationFailed(f"Dataset '{dataset}' has no builder")
    rows, totals, warnings = await builder(project, filters, permissions)

    keys = {c.key for c in columns}
    projected = [{k: v for k, v in row.items() if k in keys} for row in rows]
    truncated = len(projected) > limit
    return ReportPreview(
        dataset=dataset, columns=[c.describe() for c in columns],
        rows=projected[:limit], total_rows=len(projected), truncated=truncated,
        snapshot_id=f"snap-{new_id()[:12]}", generated_at=utcnow(),
        applied_permissions=sorted(str(p) for p in permissions),
        warnings=warnings + (["Row limit reached; refine the filters or run an "
                              "asynchronous export."] if truncated else []),
        totals=totals,
    )


# --- dataset builders -------------------------------------------------------

Builder = Callable[[Project, dict[str, Any], set[Permission]],
                   Awaitable[tuple[list[dict[str, Any]], dict[str, Any], list[str]]]]


async def _backlog(project: Project, filters: dict[str, Any],
                   permissions: set[Permission]):
    query: dict[str, Any] = {"projectId": project.id}
    if filters.get("approvalState"):
        query["state"] = filters["approvalState"]
    if filters.get("type"):
        query["type"] = filters["type"]
    if filters.get("executionStatus"):
        query["executionStatus"] = filters["executionStatus"]
    if filters.get("iterationId"):
        query["iterationId"] = filters["iterationId"]
    if filters.get("rootId"):
        query["$or"] = [{"_id": filters["rootId"]}, {"path": filters["rootId"]}]

    items = await backlog_items.list(query, sort=[("order", 1)])
    by_id = {i.id: i for i in items}
    versions = await artifact_versions.list(
        {"_id": {"$in": [i.current_version_id for i in items if i.current_version_id]}})
    version_by_item = {v.item_id: v for v in versions}
    estimate_rows = await estimates.list({"projectId": project.id, "superseded": False,
                                          "isRoughParent": False})
    estimate_by_item = {e.item_id: e for e in estimate_rows}
    test_rows = await test_cases.aggregate([
        {"$match": {"projectId": project.id}},
        {"$group": {"_id": "$storyId", "n": {"$sum": 1}}}])
    tests_by_item = {r["_id"]: r["n"] for r in test_rows if r["_id"]}
    card = await effective_rate_card(project.id)

    rows: list[dict[str, Any]] = []
    total_hours_sum = 0.0
    for item in items:
        version = version_by_item.get(item.id)
        estimate = estimate_by_item.get(item.id)
        hours = total_hours(estimate) if estimate else 0.0
        total_hours_sum += hours
        cost = None
        if card and estimate:
            cost = estimate_cost(role_breakdown(estimate), card).amount
        parent = by_id.get(item.parent_id or "")
        rows.append({
            "id": item.id, "stableId": item.stable_id, "type": str(item.type),
            "title": item.title,
            "parentStableId": parent.stable_id if parent else None,
            "state": str(item.state), "executionStatus": str(item.execution_status),
            "priority": str(item.priority), "version": item.current_version,
            "approvedVersion": item.approved_version,
            "storyPoints": estimate.story_points if estimate else None,
            "effortHours": hours,
            "effortDays": round(hours / project.calendar.hours_per_person_day, 2)
            if hours else 0.0,
            "estimatedCost": cost,
            "criteriaCount": len(version.acceptance_criteria) if version else 0,
            "testCount": tests_by_item.get(item.id, 0),
            "ownerId": item.owner_id,
        })
    totals = {"effortHours": round(total_hours_sum, 2),
              "effortDays": round(total_hours_sum / project.calendar.hours_per_person_day, 2),
              "items": len(rows)}
    warnings = [] if card else ["No effective rate card: cost columns are empty."]
    return rows, totals, warnings


async def _estimates_by_role(project: Project, filters: dict[str, Any],
                             permissions: set[Permission]):
    items = {i.id: i for i in await backlog_items.list({"projectId": project.id})}
    rows_out: list[dict[str, Any]] = []
    card = await effective_rate_card(project.id)
    totals: dict[str, float] = {}
    for estimate in await estimates.list({"projectId": project.id, "superseded": False}):
        item = items.get(estimate.item_id)
        if not item:
            continue
        for role, hours in role_breakdown(estimate).items():
            rate = card.rates.get(role) if card else None
            rows_out.append({
                "stableId": item.stable_id, "title": item.title, "role": role,
                "hours": hours, "lowHours": estimate.low_hours,
                "highHours": estimate.high_hours, "method": str(estimate.method),
                "confidenceLabel": estimate.confidence_label,
                "rate": rate,
                "cost": round(float(rate) * hours, 2) if rate else None,
            })
            totals[role] = round(totals.get(role, 0.0) + hours, 2)
    return rows_out, {"hoursByRole": totals}, []


async def _planned_vs_actual(project: Project, filters: dict[str, Any],
                             permissions: set[Permission]):
    items = await backlog_items.list({"projectId": project.id})
    estimate_rows = await estimates.list({"projectId": project.id, "superseded": False,
                                          "isRoughParent": False})
    by_item = {e.item_id: e for e in estimate_rows}
    logs = await worklogs.aggregate([
        {"$match": {"projectId": project.id, "approved": True}},
        {"$group": {"_id": "$itemId", "hours": {"$sum": "$hours"}}}])
    actual_by_item = {r["_id"]: round(r["hours"], 2) for r in logs}
    rows: list[dict[str, Any]] = []
    for item in items:
        estimate = by_item.get(item.id)
        planned = total_hours(estimate) if estimate else 0.0
        actual = actual_by_item.get(item.id, 0.0)
        done = str(item.execution_status) == "done"
        rows.append({
            "stableId": item.stable_id, "title": item.title,
            "plannedHours": planned, "actualHours": actual,
            "remainingHours": 0.0 if done else round(max(planned - actual, 0.0), 2),
            "executionStatus": str(item.execution_status),
        })
    totals = {
        "plannedHours": round(sum(r["plannedHours"] for r in rows), 2),
        "actualHours": round(sum(r["actualHours"] for r in rows), 2),
        "remainingHours": round(sum(r["remainingHours"] for r in rows), 2),
    }
    return rows, totals, ["Remaining effort is reviewed remaining work, not planned "
                          "minus consumed."]


async def _cost_forecast(project: Project, filters: dict[str, Any],
                         permissions: set[Permission]):
    if Permission.COST_READ not in permissions:
        raise Forbidden("Cost data requires the cost.read permission")
    from app.services.estimation import cost_summary
    summary = await cost_summary(project.id, currency=project.currency,
                                 hours_per_person_day=project.calendar.hours_per_person_day)
    rows = [
        {"category": "Estimated labour cost",
         "amount": summary.estimated_cost.amount if summary.estimated_cost else "0.00",
         "currency": project.currency, "note": "Current detailed rollup"},
        {"category": "Actual labour cost",
         "amount": summary.actual_cost.amount if summary.actual_cost else "0.00",
         "currency": project.currency, "note": "Approved time entries at the rate "
                                               "effective on the work date"},
        {"category": "Remaining forecast",
         "amount": summary.remaining_forecast.amount if summary.remaining_forecast
         else "0.00",
         "currency": project.currency, "note": "Reviewed remaining effort"},
        {"category": "Forecast at completion",
         "amount": summary.forecast_at_completion.amount
         if summary.forecast_at_completion else "0.00",
         "currency": project.currency, "note": "Actual to date plus remaining forecast"},
    ]
    return rows, {}, summary.warnings


async def _capacity(project: Project, filters: dict[str, Any],
                    permissions: set[Permission]):
    from datetime import date, timedelta

    from app.services.estimation import capacity
    start = date.fromisoformat(filters["from"]) if filters.get("from") else \
        utcnow().date()
    end = date.fromisoformat(filters["to"]) if filters.get("to") else \
        start + timedelta(days=28)
    rows = await capacity(
        project.id, start, end,
        working_days=project.calendar.working_days,
        hours_per_person_day=project.calendar.hours_per_person_day,
        holidays=project.calendar.holidays, focus_factor=project.calendar.focus_factor,
        allocation_includes_focus=project.calendar.allocation_includes_focus)
    data = [r.model_dump(by_alias=True) for r in rows]
    totals = {"availableHours": round(sum(r.available_hours for r in rows), 2)}
    return data, totals, []


async def _sprint_progress(project: Project, filters: dict[str, Any],
                           permissions: set[Permission]):
    rows: list[dict[str, Any]] = []
    for iteration in await iterations.list({"projectId": project.id},
                                           sort=[("startDate", 1)]):
        items = await backlog_items.list({"projectId": project.id,
                                          "iterationId": iteration.id})
        done = [i for i in items if str(i.execution_status) == "done"]
        estimate_rows = await estimates.list({"projectId": project.id,
                                              "superseded": False,
                                              "itemId": {"$in": [i.id for i in items]}})
        completed = sum(e.story_points or 0.0 for e in estimate_rows
                        if e.item_id in {i.id for i in done})
        rows.append({
            "name": iteration.name, "state": str(iteration.state),
            "startDate": iteration.start_date, "endDate": iteration.end_date,
            "capacityHours": iteration.capacity_hours,
            "committedPoints": round(sum(e.story_points or 0.0 for e in estimate_rows), 2),
            "completedPoints": round(completed, 2),
            "itemCount": len(items), "doneCount": len(done),
        })
    return rows, {}, []


async def _kanban_flow(project: Project, filters: dict[str, Any],
                       permissions: set[Permission]):
    items = await backlog_items.list({"projectId": project.id})
    events = await status_events.list({"projectId": project.id}, sort=[("at", 1)])
    entered: dict[str, Any] = {}
    for event in events:
        entered[event.item_id] = event.at
    now = utcnow()
    rows = [{
        "stableId": item.stable_id, "title": item.title,
        "column": item.kanban_column or str(item.execution_status),
        "enteredAt": entered.get(item.id),
        "ageDays": round((now - entered[item.id]).total_seconds() / 86400, 2)
        if item.id in entered else None,
        "blockedReason": item.blocked_reason, "serviceClass": item.service_class,
    } for item in items if str(item.execution_status) not in ("done", "cancelled")]
    return rows, {"workInProgress": len(rows)}, []


async def _traceability(project: Project, filters: dict[str, Any],
                        permissions: set[Permission]):
    from app.repositories import source_documents, source_versions
    links = await evidence_links.list({"projectId": project.id}, limit=20000)
    versions = {v.id: v for v in await source_versions.list({"projectId": project.id})}
    documents = {d.id: d for d in await source_documents.list({"projectId": project.id})}
    items = {i.id: i for i in await backlog_items.list({"projectId": project.id})}
    rows: list[dict[str, Any]] = []
    for link in links:
        version = versions.get(link.source_version_id or "")
        document = documents.get(version.document_id) if version else None
        target = items.get(link.target_id)
        locator = link.locator or {}
        rows.append({
            "sourceTitle": document.title if document else "Unavailable evidence",
            "locator": f"{locator.get('kind', '')}:{locator.get('value', '')}",
            "targetType": link.target_type,
            "targetStableId": target.stable_id if target else link.target_id,
            "targetTitle": target.title if target else None,
            "linkType": str(link.link_type),
        })
    return rows, {"links": len(rows)}, []


async def _testbook(project: Project, filters: dict[str, Any],
                    permissions: set[Permission]):
    items = {i.id: i for i in await backlog_items.list({"projectId": project.id})}
    rows = []
    for case in await test_cases.list({"projectId": project.id}):
        story = items.get(case.story_id or "")
        rows.append({
            "stableId": case.stable_id, "title": case.title,
            "storyStableId": story.stable_id if story else None,
            "criterionIds": ", ".join(case.criterion_ids),
            "testType": str(case.test_type), "priority": str(case.priority),
            "state": str(case.state), "reviewState": case.review_state,
            "hasGherkin": case.gherkin is not None,
        })
    return rows, {"tests": len(rows)}, ["No run status is implied by generation."]


async def _approval_history(project: Project, filters: dict[str, Any],
                            permissions: set[Permission]):
    items = {i.id: i for i in await backlog_items.list({"projectId": project.id})}
    rows = []
    for event in await approval_events.list({"projectId": project.id},
                                            sort=[("decidedAt", -1)]):
        root = items.get(event.root_id)
        rows.append({
            "decidedAt": event.decided_at, "decision": str(event.decision),
            "rootStableId": root.stable_id if root else event.root_id,
            "rootType": event.root_type, "entries": len(event.entries),
            "inherited": sum(1 for e in event.entries if e.inherited),
            "waivers": len(event.waivers), "decidedBy": event.decided_by,
            "revoked": event.revoked,
        })
    return rows, {"events": len(rows)}, []


async def _change_impact(project: Project, filters: dict[str, Any],
                         permissions: set[Permission]):
    rows = []
    for request in await change_requests.list({"projectId": project.id},
                                              sort=[("createdAt", -1)]):
        rows.append({
            "stableId": request.stable_id, "title": request.title,
            "status": str(request.status), "origin": request.origin,
            "affectedItems": len(request.affected_item_ids),
            "effortDeltaHours": request.effort_delta_hours,
            "dateImpactDays": request.date_impact_days,
            "costDelta": request.cost_delta.amount if request.cost_delta else None,
        })
    return rows, {"changes": len(rows)}, []


async def _connector_health(project: Project, filters: dict[str, Any],
                            permissions: set[Permission]):
    rows = await integration_service.health(project.id)
    return rows, {"connectors": len(rows)}, []


async def _questions(project: Project, filters: dict[str, Any],
                     permissions: set[Permission]):
    query: dict[str, Any] = {"projectId": project.id}
    if filters.get("status"):
        query["status"] = filters["status"]
    if filters.get("severity"):
        query["severity"] = filters["severity"]
    rows = [{
        "stableId": q.stable_id, "title": q.title, "severity": str(q.severity),
        "kind": str(q.kind), "status": str(q.status), "ownerId": q.owner_id,
        "answer": q.answer,
    } for q in await questions.list(query, sort=[("severity", 1)])]
    return rows, {"questions": len(rows)}, []


BUILDERS: dict[str, Builder] = {
    ReportDataset.BACKLOG: _backlog,
    ReportDataset.ESTIMATES_BY_ROLE: _estimates_by_role,
    ReportDataset.PLANNED_VS_ACTUAL: _planned_vs_actual,
    ReportDataset.COST_FORECAST: _cost_forecast,
    ReportDataset.CAPACITY: _capacity,
    ReportDataset.SPRINT_PROGRESS: _sprint_progress,
    ReportDataset.KANBAN_FLOW: _kanban_flow,
    ReportDataset.TRACEABILITY: _traceability,
    ReportDataset.TESTBOOK: _testbook,
    ReportDataset.APPROVAL_HISTORY: _approval_history,
    ReportDataset.CHANGE_IMPACT: _change_impact,
    ReportDataset.CONNECTOR_HEALTH: _connector_health,
    ReportDataset.QUESTIONS: _questions,
}


def templates() -> list[dict[str, Any]]:
    """REQ-REPORT-02 — the required template catalogue."""
    labels = {
        ReportDataset.BACKLOG: "Backlog",
        ReportDataset.ESTIMATES_BY_ROLE: "Estimates by role",
        ReportDataset.PLANNED_VS_ACTUAL: "Planned versus actual effort",
        ReportDataset.COST_FORECAST: "Cost forecast",
        ReportDataset.CAPACITY: "Capacity",
        ReportDataset.SPRINT_PROGRESS: "Sprint progress",
        ReportDataset.KANBAN_FLOW: "Kanban flow",
        ReportDataset.TRACEABILITY: "Traceability",
        ReportDataset.TESTBOOK: "Testbook",
        ReportDataset.APPROVAL_HISTORY: "Approval history",
        ReportDataset.CHANGE_IMPACT: "Change impact",
        ReportDataset.CONNECTOR_HEALTH: "Connector health",
        ReportDataset.QUESTIONS: "Open questions",
    }
    return [{"dataset": str(dataset), "name": name,
             "columns": [c.describe() for c in COLUMNS[dataset]]}
            for dataset, name in labels.items()]
