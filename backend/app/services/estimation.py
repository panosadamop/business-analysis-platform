"""Estimation, rollup and costing (section 11).

The formulas here are the specification's formulas, implemented literally:

* role effort            person_hours[r]
* total effort           sum(person_hours[r]) + explicit_overhead_hours
* person days            total_person_hours / project_hours_per_person_day
* estimated labour cost  sum(person_hours[r] x effective_hourly_rate[r])
* actual labour cost     sum(approved_hours x rate effective on the work date)
* forecast at completion actual to date + forecast remaining

A parent's initial rough estimate is kept for comparison and never added to the
child rollup (section 11.2, AT-12).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Iterable

from app.core.errors import NotFound
from app.core.utils import decimal_sum, money, utcnow
from app.models.backlog import (Estimate, EstimateCreate, EstimateRollup,
                                RateCard)
from app.models.common import ItemType, Money
from app.models.planning import CapacityRow, CostSummary
from app.repositories import (allocations, backlog_items, estimates, leaves,
                              members, rate_cards, users, worklogs)
from app.services import audit


def total_hours(estimate: Estimate) -> float:
    """sum(person_hours[r]) + explicit_overhead_hours."""
    return round(sum(r.hours for r in estimate.role_efforts) + estimate.overhead_hours, 2)


def role_breakdown(estimate: Estimate) -> dict[str, float]:
    breakdown: dict[str, float] = {}
    for role_effort in estimate.role_efforts:
        breakdown[role_effort.role] = round(
            breakdown.get(role_effort.role, 0.0) + role_effort.hours, 2)
    return breakdown


def person_days(hours: float, hours_per_person_day: float) -> float:
    if hours_per_person_day <= 0:
        return 0.0
    return round(hours / hours_per_person_day, 2)


async def current_estimate(project_id: str, item_id: str, *,
                           rough_parent: bool = False) -> Estimate | None:
    found = await estimates.list(
        {"projectId": project_id, "itemId": item_id, "superseded": False,
         "isRoughParent": rough_parent},
        sort=[("createdAt", -1)], limit=1)
    return found[0] if found else None


async def save_estimate(project_id: str, item_id: str, payload: EstimateCreate, *,
                        actor_id: str) -> Estimate:
    item = await backlog_items.get(item_id, projectId=project_id)
    if not item:
        raise NotFound("Backlog item not found")

    previous = await current_estimate(project_id, item_id,
                                      rough_parent=payload.is_rough_parent)
    if previous:
        # Old estimates are never overwritten (section 11.4).
        await estimates.update(previous.id, {"superseded": True})

    estimate = Estimate(
        project_id=project_id, item_id=item_id, item_version=item.current_version,
        method=payload.method, estimator_id=actor_id, estimated_at=utcnow(),
        story_points=payload.story_points, role_efforts=payload.role_efforts,
        overhead_hours=payload.overhead_hours, low_hours=payload.low_hours,
        likely_hours=payload.likely_hours, high_hours=payload.high_hours,
        confidence_label=payload.confidence_label, assumptions=payload.assumptions,
        unknown=payload.unknown, spike_required=payload.spike_required,
        is_rough_parent=payload.is_rough_parent, note=payload.note,
    )
    await estimates.insert(estimate)
    await audit.record("estimate.saved", project_id=project_id, actor_id=actor_id,
                       object_type="estimate", object_id=estimate.id,
                       detail={"itemId": item_id, "hours": total_hours(estimate),
                               "points": payload.story_points,
                               "roughParent": payload.is_rough_parent})
    return estimate


def inconsistency_warnings(estimate: Estimate) -> list[str]:
    """Points and effort stay independent; inconsistency is warned, not forced."""
    warnings: list[str] = []
    hours = total_hours(estimate)
    if estimate.story_points is not None and estimate.story_points > 0 and hours == 0:
        warnings.append("Story points are set but no role effort is recorded.")
    if hours > 0 and estimate.story_points in (None, 0):
        warnings.append("Role effort is recorded but no story points are set.")
    if estimate.low_hours is not None and estimate.high_hours is not None:
        if estimate.low_hours > estimate.high_hours:
            warnings.append("The low estimate is greater than the high estimate.")
        if hours and not (estimate.low_hours <= hours <= estimate.high_hours):
            warnings.append("The likely effort sits outside the low to high range.")
    if estimate.unknown and hours:
        warnings.append("The estimate is marked unknown but carries effort values.")
    return warnings


async def rollup(project_id: str, item_id: str, *, hours_per_person_day: float = 8.0,
                 rate_card: RateCard | None = None,
                 include_cost: bool = True) -> EstimateRollup:
    """Detailed rollup for an item, following section 11.2."""
    item = await backlog_items.get(item_id, projectId=project_id)
    if not item:
        raise NotFound("Backlog item not found")

    descendants = await backlog_items.list({"projectId": project_id, "path": item_id})
    all_ids = [item_id] + [d.id for d in descendants]
    rows = await estimates.list({"projectId": project_id, "itemId": {"$in": all_ids},
                                 "superseded": False})

    own = next((e for e in rows if e.item_id == item_id and not e.is_rough_parent), None)
    rough = next((e for e in rows if e.item_id == item_id and e.is_rough_parent), None)
    child_estimates = [e for e in rows if e.item_id != item_id and not e.is_rough_parent]

    own_hours = total_hours(own) if own else 0.0
    own_overhead = own.overhead_hours if own else 0.0
    children_hours = round(sum(total_hours(e) for e in child_estimates), 2)

    # Parent own effort is explicit overhead only; child work is not duplicated.
    has_children = bool(descendants)
    detailed = round((own_overhead if has_children else own_hours) + children_hours, 2)

    breakdown: dict[str, float] = {}
    for estimate in ([own] if own and not has_children else []) + child_estimates:
        if not estimate:
            continue
        for role, hours in role_breakdown(estimate).items():
            breakdown[role] = round(breakdown.get(role, 0.0) + hours, 2)

    low = round(sum((e.low_hours if e.low_hours is not None else total_hours(e))
                    for e in child_estimates) + (own_overhead if has_children else
                                                 (own.low_hours or own_hours if own else 0.0)), 2)
    high = round(sum((e.high_hours if e.high_hours is not None else total_hours(e))
                     for e in child_estimates) + (own_overhead if has_children else
                                                  (own.high_hours or own_hours if own else 0.0)), 2)

    points: float | None = None
    comparable = True
    teams = {d.labels[0] for d in descendants if d.labels} or set()
    if item.type == ItemType.STORY and own and own.story_points is not None:
        points = own.story_points
    else:
        child_points = [e.story_points for e in child_estimates if e.story_points is not None]
        points = round(sum(child_points), 2) if child_points else None
        comparable = len(teams) <= 1

    warnings: list[str] = []
    if rough and detailed:
        warnings.append(
            f"Initial rough estimate {rough.likely_hours or total_hours(rough)}h is kept "
            f"for comparison only; the detailed rollup is {detailed}h.")
    if not comparable:
        warnings.append("Story points span multiple teams and are not comparable without "
                        "a validated normalisation.")
    if low or high:
        warnings.append("Range totals are sums of bounds, not statistical confidence "
                        "intervals.")
    estimated_children = len({e.item_id for e in child_estimates})
    if has_children and estimated_children < len(descendants):
        warnings.append(f"{len(descendants) - estimated_children} descendant(s) have no "
                        "estimate yet; the rollup is incomplete.")

    cost: Money | None = None
    if include_cost and rate_card:
        cost = estimate_cost(breakdown, rate_card)

    return EstimateRollup(
        item_id=item_id, hours_per_person_day=hours_per_person_day,
        own_hours=own_hours, own_overhead_hours=own_overhead,
        children_hours=children_hours, detailed_hours=detailed,
        rough_parent_hours=(rough.likely_hours or total_hours(rough)) if rough else None,
        low_hours=low, high_hours=high,
        person_days=person_days(detailed, hours_per_person_day),
        story_points=points, story_points_comparable=comparable,
        estimated_cost=cost, role_breakdown=breakdown, warnings=warnings,
        children_estimated=estimated_children, children_total=len(descendants),
    )


def estimate_cost(breakdown: dict[str, float], rate_card: RateCard) -> Money:
    """sum(person_hours[r] x effective_hourly_rate[r])."""
    total = Decimal("0")
    for role, hours in breakdown.items():
        rate = rate_card.rates.get(role)
        if rate is None:
            continue
        total += Decimal(str(hours)) * Decimal(rate)
    if rate_card.contingency_percent:
        total *= (Decimal("1") + Decimal(str(rate_card.contingency_percent)) / Decimal("100"))
    for line in rate_card.non_labor_lines:
        total += Decimal(str(line.get("amount", 0)))
    return Money.of(total, rate_card.currency)


async def effective_rate_card(project_id: str, on: date | None = None) -> RateCard | None:
    """Rate cards are effective dated; the one covering ``on`` wins."""
    target = on or utcnow().date()
    cards = await rate_cards.list({"projectId": project_id}, sort=[("effectiveFrom", -1)])
    for card in cards:
        if card.effective_from <= target and (card.effective_to is None
                                              or card.effective_to >= target):
            return card
    return cards[0] if cards else None


async def actual_cost(project_id: str, *, currency: str = "EUR",
                      only_approved: bool = True) -> Money:
    """sum(approved_time_entry_hours x rate_effective_on_work_date)."""
    query: dict[str, Any] = {"projectId": project_id}
    if only_approved:
        query["approved"] = True
    entries = await worklogs.list(query)
    cards = await rate_cards.list({"projectId": project_id}, sort=[("effectiveFrom", 1)])
    total = Decimal("0")
    for entry in entries:
        rate = _rate_on(cards, entry.role, entry.work_date)
        if rate is None:
            continue
        total += Decimal(str(entry.hours)) * rate
    return Money.of(total, currency)


def _rate_on(cards: Iterable[RateCard], role: str | None, on: date) -> Decimal | None:
    if not role:
        return None
    chosen: Decimal | None = None
    for card in cards:
        if card.effective_from <= on and (card.effective_to is None or card.effective_to >= on):
            value = card.rates.get(role)
            if value is not None:
                chosen = Decimal(value)
    return chosen


async def actual_hours(project_id: str, *, only_approved: bool = True) -> float:
    query: dict[str, Any] = {"projectId": project_id}
    if only_approved:
        query["approved"] = True
    rows = await worklogs.aggregate([
        {"$match": query},
        {"$group": {"_id": None, "hours": {"$sum": "$hours"}}},
    ])
    return round(rows[0]["hours"], 2) if rows else 0.0


async def cost_summary(project_id: str, *, currency: str, hours_per_person_day: float,
                       baseline_budget: Money | None = None) -> CostSummary:
    """Forecast at completion = actual to date + forecast remaining (section 11.3)."""
    roots = await backlog_items.list({"projectId": project_id, "parentId": None})
    card = await effective_rate_card(project_id)
    warnings: list[str] = []

    estimated = Decimal("0")
    remaining_hours = 0.0
    for root in roots:
        result = await rollup(project_id, root.id,
                              hours_per_person_day=hours_per_person_day, rate_card=card)
        if result.estimated_cost:
            estimated += result.estimated_cost.value
        remaining_hours += result.detailed_hours
        warnings.extend(w for w in result.warnings if w not in warnings)

    spent = await actual_hours(project_id)
    actual = await actual_cost(project_id, currency=currency)

    # Remaining forecast is reviewed remaining effort, independent of hours spent.
    done_items = await backlog_items.list({"projectId": project_id,
                                           "executionStatus": "done"})
    done_ids = {i.id for i in done_items}
    completed_hours = 0.0
    if done_ids:
        rows = await estimates.list({"projectId": project_id, "superseded": False,
                                     "itemId": {"$in": list(done_ids)}})
        completed_hours = round(sum(total_hours(e) for e in rows), 2)
    forecast_remaining_hours = max(remaining_hours - completed_hours, 0.0)

    remaining_cost = Money.of(0, currency)
    if card and forecast_remaining_hours and remaining_hours:
        ratio = Decimal(str(forecast_remaining_hours)) / Decimal(str(remaining_hours or 1))
        remaining_cost = Money.of(estimated * ratio, currency)
    if not card:
        warnings.append("No effective rate card is configured; cost values are not computed.")

    forecast = Money.of(actual.value + remaining_cost.value, currency)
    if spent and not await worklogs.exists({"projectId": project_id, "approved": False}):
        pass
    unapproved = await worklogs.count({"projectId": project_id, "approved": False})
    if unapproved:
        warnings.append(f"{unapproved} time entries are not approved and are excluded "
                        "from actual cost.")

    return CostSummary(
        currency=currency,
        baseline_budget=baseline_budget,
        estimated_cost=Money.of(estimated, currency),
        actual_cost=actual,
        forecast_at_completion=forecast,
        remaining_forecast=remaining_cost,
        warnings=warnings,
    )


async def capacity(project_id: str, start: date, end: date, *,
                   working_days: list[int], hours_per_person_day: float,
                   holidays: list[date], focus_factor: float,
                   allocation_includes_focus: bool) -> list[CapacityRow]:
    """available = scheduled working hours - leave, x allocation x focus factor.

    The focus factor is never applied twice when allocations already represent
    productive hours (section 11.3).
    """
    project_members = await members.list({"projectId": project_id, "revokedAt": None})
    user_ids = [m.user_id for m in project_members]
    people = {u.id: u for u in await users.list({"_id": {"$in": user_ids}})}
    member_allocations = await allocations.list({"projectId": project_id})
    leave_rows = await leaves.list({"userId": {"$in": user_ids}})

    working = _working_days_between(start, end, working_days, holidays)
    rows: list[CapacityRow] = []
    for member in project_members:
        person = people.get(member.user_id)
        if not person:
            continue
        allocation = next(
            (a.percent for a in member_allocations
             if a.user_id == member.user_id and a.start_date <= end and a.end_date >= start),
            member.allocation_percent)
        leave_days = sum(
            len(_working_days_between(max(l.start_date, start), min(l.end_date, end),
                                      working_days, holidays))
            for l in leave_rows
            if l.user_id == member.user_id and l.start_date <= end and l.end_date >= start)
        scheduled = len(working) * hours_per_person_day
        leave_hours = leave_days * hours_per_person_day
        effective_focus = 1.0 if allocation_includes_focus else focus_factor
        available = max(scheduled - leave_hours, 0.0) * (allocation / 100.0) * effective_focus
        rows.append(CapacityRow(
            user_id=member.user_id, display_name=person.display_name,
            role=member.delivery_role, period_start=start, period_end=end,
            scheduled_hours=round(scheduled, 2), leave_hours=round(leave_hours, 2),
            allocation_percent=allocation, focus_factor=effective_focus,
            available_hours=round(available, 2),
        ))
    return rows


def _working_days_between(start: date, end: date, working_days: list[int],
                          holidays: list[date]) -> list[date]:
    from datetime import timedelta

    days: list[date] = []
    holiday_set = set(holidays)
    cursor = start
    while cursor <= end:
        if cursor.isoweekday() in working_days and cursor not in holiday_set:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


async def cross_project_allocation_warnings(user_ids: list[str],
                                            threshold: float = 100.0) -> list[dict]:
    """Validate cumulative staff allocation across projects (section 11.3)."""
    rows = await allocations.aggregate([
        {"$match": {"userId": {"$in": user_ids}}},
        {"$group": {"_id": "$userId", "total": {"$sum": "$percent"},
                    "projects": {"$addToSet": "$projectId"}}},
    ])
    return [
        {"userId": row["_id"], "totalPercent": row["total"],
         "projects": row["projects"],
         "message": f"Allocated {row['total']}% across {len(row['projects'])} projects"}
        for row in rows if row["total"] > threshold
    ]
