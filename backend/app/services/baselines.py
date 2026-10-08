"""Baselines and change requests (section 10.3).

A baseline is an immutable snapshot of scope, estimates, schedule and rates.
Comparisons are always explicit about which of original baseline, current
approved plan and latest forecast they use.
"""
from __future__ import annotations

from typing import Any

from app.core.errors import ConflictState, NotFound
from app.core.utils import utcnow
from app.models.approval import (Baseline, BaselineComparison, BaselineCreate,
                                 ChangeRequest, ChangeRequestCreate,
                                 ChangeRequestDecide, ChangeRequestStatus)
from app.models.common import Money
from app.models.project import Project
from app.repositories import (approval_events, backlog_items, baselines,
                              change_requests, estimates, milestones,
                              rate_cards)
from app.services import audit
from app.services.estimation import (effective_rate_card, estimate_cost,
                                     role_breakdown, total_hours)


async def create(project: Project, payload: BaselineCreate, *,
                 actor_id: str) -> Baseline:
    items = await backlog_items.list({"projectId": project.id}, sort=[("order", 1)])
    rows = await estimates.list({"projectId": project.id, "superseded": False,
                                 "isRoughParent": False})
    by_item = {e.item_id: e for e in rows}
    card = await effective_rate_card(project.id)

    snapshot: list[dict[str, Any]] = []
    total = 0.0
    points = 0.0
    cost = Money.of(0, project.currency)
    for item in items:
        estimate = by_item.get(item.id)
        hours = total_hours(estimate) if estimate else 0.0
        total += hours
        points += (estimate.story_points or 0.0) if estimate else 0.0
        item_cost = (estimate_cost(role_breakdown(estimate), card)
                     if card and estimate else None)
        if item_cost:
            cost = cost.plus(item_cost)
        snapshot.append({
            "itemId": item.id, "stableId": item.stable_id, "type": str(item.type),
            "parentId": item.parent_id, "title": item.title,
            "version": item.current_version, "approvedVersion": item.approved_version,
            "state": str(item.state), "effortHours": hours,
            "storyPoints": estimate.story_points if estimate else None,
            "estimatedCost": item_cost.amount if item_cost else None,
        })

    schedule = [{"milestoneId": m.id, "name": m.name, "dueDate": m.due_date,
                 "baselineDate": m.baseline_date or m.due_date}
                for m in await milestones.list({"projectId": project.id})]

    baseline = Baseline(
        project_id=project.id, name=payload.name, description=payload.description,
        created_by=actor_id, approval_event_id=payload.approval_event_id,
        items=snapshot,
        totals={"detailedHours": round(total, 2), "storyPoints": round(points, 2),
                "cost": cost.amount, "items": len(snapshot),
                "personDays": round(total / project.calendar.hours_per_person_day, 2)},
        rate_card_id=card.id if card else None, schedule=schedule,
        currency=project.currency,
        hours_per_person_day=project.calendar.hours_per_person_day,
    )
    await baselines.insert(baseline)
    await audit.record("baseline.created", project_id=project.id, actor_id=actor_id,
                       object_type="baseline", object_id=baseline.id,
                       detail={"name": payload.name, "items": len(snapshot),
                               "hours": baseline.totals["detailedHours"]})
    return baseline


async def compare(project: Project, baseline_id: str) -> BaselineComparison:
    baseline = await baselines.get(baseline_id, projectId=project.id)
    if not baseline:
        raise NotFound("Baseline not found")

    current = await create_dry_run(project)
    before = {row["itemId"]: row for row in baseline.items}
    after = {row["itemId"]: row for row in current["items"]}

    added = [row for item_id, row in after.items() if item_id not in before]
    removed = [row for item_id, row in before.items() if item_id not in after]
    changed: list[dict[str, Any]] = []
    for item_id, row in after.items():
        old = before.get(item_id)
        if not old:
            continue
        diffs = {key: {"from": old.get(key), "to": row.get(key)}
                 for key in ("title", "effortHours", "storyPoints", "state",
                             "approvedVersion", "estimatedCost")
                 if old.get(key) != row.get(key)}
        if diffs:
            changed.append({"itemId": item_id, "stableId": row["stableId"],
                            "title": row["title"], "changes": diffs})

    delta = {
        "detailedHours": round(current["totals"]["detailedHours"]
                               - baseline.totals.get("detailedHours", 0.0), 2),
        "storyPoints": round(current["totals"]["storyPoints"]
                             - baseline.totals.get("storyPoints", 0.0), 2),
        "items": current["totals"]["items"] - baseline.totals.get("items", 0),
    }
    return BaselineComparison(
        baseline_id=baseline.id, baseline_name=baseline.name, as_of=utcnow(),
        added=added, removed=removed, changed=changed,
        totals_baseline=baseline.totals, totals_current=current["totals"], delta=delta)


async def create_dry_run(project: Project) -> dict[str, Any]:
    """Current plan snapshot used for comparison without persisting a baseline."""
    items = await backlog_items.list({"projectId": project.id}, sort=[("order", 1)])
    rows = await estimates.list({"projectId": project.id, "superseded": False,
                                 "isRoughParent": False})
    by_item = {e.item_id: e for e in rows}
    card = await effective_rate_card(project.id)
    snapshot: list[dict[str, Any]] = []
    total = points = 0.0
    cost = Money.of(0, project.currency)
    for item in items:
        estimate = by_item.get(item.id)
        hours = total_hours(estimate) if estimate else 0.0
        total += hours
        points += (estimate.story_points or 0.0) if estimate else 0.0
        item_cost = (estimate_cost(role_breakdown(estimate), card)
                     if card and estimate else None)
        if item_cost:
            cost = cost.plus(item_cost)
        snapshot.append({
            "itemId": item.id, "stableId": item.stable_id, "type": str(item.type),
            "parentId": item.parent_id, "title": item.title,
            "version": item.current_version, "approvedVersion": item.approved_version,
            "state": str(item.state), "effortHours": hours,
            "storyPoints": estimate.story_points if estimate else None,
            "estimatedCost": item_cost.amount if item_cost else None,
        })
    return {"items": snapshot,
            "totals": {"detailedHours": round(total, 2), "storyPoints": round(points, 2),
                       "cost": cost.amount, "items": len(snapshot),
                       "personDays": round(total / project.calendar.hours_per_person_day,
                                           2)}}


async def create_change_request(project: Project, payload: ChangeRequestCreate, *,
                                actor_id: str) -> ChangeRequest:
    index = await change_requests.count({"projectId": project.id}) + 1
    card = await effective_rate_card(project.id)
    cost_delta = None
    if card and payload.effort_delta_hours:
        # Uses the blended rate of the roles present on the card.
        rates = [float(v) for v in card.rates.values()]
        blended = sum(rates) / len(rates) if rates else 0.0
        cost_delta = Money.of(payload.effort_delta_hours * blended, card.currency)

    request = ChangeRequest(
        project_id=project.id, stable_id=f"CR-{index:03d}", title=payload.title,
        reason=payload.reason, baseline_id=payload.baseline_id, raised_by=actor_id,
        origin=payload.origin, evidence_refs=payload.evidence_refs,
        affected_item_ids=payload.affected_item_ids,
        effort_delta_hours=payload.effort_delta_hours, cost_delta=cost_delta,
        date_impact_days=payload.date_impact_days,
    )
    await change_requests.insert(request)
    await audit.record("change_request.created", project_id=project.id, actor_id=actor_id,
                       object_type="changeRequest", object_id=request.id,
                       detail={"stableId": request.stable_id,
                               "effortDeltaHours": payload.effort_delta_hours})
    return request


async def decide_change_request(project_id: str, request_id: str,
                                payload: ChangeRequestDecide, *,
                                actor_id: str) -> ChangeRequest:
    request = await change_requests.require(request_id, projectId=project_id)
    if request.status in (ChangeRequestStatus.APPROVED, ChangeRequestStatus.REJECTED):
        raise ConflictState("This change request has already been decided")
    updated = await change_requests.update(request_id, {
        "status": str(payload.status), "decisionNote": payload.decision_note,
        "decidedBy": actor_id, "decidedAt": utcnow()}, projectId=project_id)

    if payload.status == ChangeRequestStatus.APPROVED and request.affected_item_ids:
        # Approving a change request does not approve artifacts; it marks the
        # affected items for renewed approval.
        await backlog_items.raw_update(
            {"_id": {"$in": request.affected_item_ids}, "approvedVersion": {"$ne": None}},
            {"$set": {"requiresReapproval": True, "updatedAt": utcnow()}})
    await audit.record("change_request.decided", project_id=project_id, actor_id=actor_id,
                       object_type="changeRequest", object_id=request_id,
                       detail={"status": str(payload.status)})
    return updated
