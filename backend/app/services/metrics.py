"""Charts and delivery metrics (section 12).

Every chart response carries its metric definition, unit, filters, as-of time
and data freshness. Units are never mixed in one series, and a forecast always
discloses whether the data supporting it is sufficient.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from app.core.utils import utcnow
from app.models.common import ItemType
from app.models.planning import ChartResponse, ChartSeries
from app.models.project import Project
from app.repositories import (backlog_items, baselines, estimates, iterations,
                              milestones, questions, status_events, test_cases,
                              worklogs, findings, boards)
from app.services.estimation import total_hours

FRESHNESS_LIVE = "live query at request time"


def _chart(name: str, title: str, unit: str, definition: str, **kwargs: Any) -> ChartResponse:
    return ChartResponse(chart=name, title=title, unit=unit, as_of=utcnow(),
                         data_freshness=FRESHNESS_LIVE, definition=definition, **kwargs)


async def planned_vs_actual(project: Project, *, baseline_id: str | None = None,
                            role: str | None = None) -> ChartResponse:
    items = await backlog_items.list({"projectId": project.id})
    rows = await estimates.list({"projectId": project.id, "superseded": False,
                                 "isRoughParent": False})
    by_item = {e.item_id: e for e in rows}
    planned = round(sum(total_hours(e) for e in rows), 2)

    baseline_hours = 0.0
    baseline_name = None
    if baseline_id:
        baseline = await baselines.get(baseline_id, projectId=project.id)
        if baseline:
            baseline_hours = baseline.totals.get("detailedHours", 0.0)
            baseline_name = baseline.name

    logs = await worklogs.list({"projectId": project.id, "approved": True})
    actual = round(sum(w.hours for w in logs), 2)

    done_ids = {i.id for i in items if str(i.execution_status) == "done"}
    completed_planned = round(sum(total_hours(e) for item_id, e in by_item.items()
                                  if item_id in done_ids), 2)
    remaining = round(max(planned - completed_planned, 0.0), 2)

    warnings: list[str] = []
    if role:
        warnings.append(f"Filtered to role '{role}'.")
    unapproved = await worklogs.count({"projectId": project.id, "approved": False})
    if unapproved:
        warnings.append(f"{unapproved} unapproved time entries are excluded from actual.")

    return _chart(
        "planned_vs_actual", "Planned versus actual effort", "person_hours",
        "Planned = current detailed estimate rollup. Actual = approved time entries. "
        "Remaining = planned effort of work not yet marked done, independent of hours "
        "already consumed.",
        categories=["baseline", "planned", "actual", "remaining"],
        series=[ChartSeries(key="effort", label="Effort", points=[
            {"category": "baseline", "value": baseline_hours, "label": baseline_name},
            {"category": "planned", "value": planned},
            {"category": "actual", "value": actual},
            {"category": "remaining", "value": remaining},
        ])],
        warnings=warnings,
        filters={"baselineId": baseline_id, "role": role},
        insufficient_data=not rows,
    )


async def burndown(project: Project, iteration_id: str, *,
                   unit: str = "story_points") -> ChartResponse:
    iteration = await iterations.get(iteration_id, projectId=project.id)
    if not iteration:
        return _chart("burndown", "Sprint burndown", unit,
                      "No iteration selected.", insufficient_data=True)

    items = await backlog_items.list({"projectId": project.id, "iterationId": iteration_id})
    rows = await estimates.list({"projectId": project.id, "superseded": False,
                                 "itemId": {"$in": [i.id for i in items]}})
    by_item = {e.item_id: e for e in rows}

    def value_of(item_id: str) -> float:
        estimate = by_item.get(item_id)
        if not estimate:
            return 0.0
        return (estimate.story_points or 0.0) if unit == "story_points" else total_hours(estimate)

    total = round(sum(value_of(i.id) for i in items), 2)
    events = await status_events.list(
        {"projectId": project.id, "itemId": {"$in": [i.id for i in items]}},
        sort=[("at", 1)])

    days: list[date] = []
    cursor = iteration.start_date
    while cursor <= iteration.end_date:
        days.append(cursor)
        cursor += timedelta(days=1)

    completed_by_day: dict[date, float] = {}
    for event in events:
        if event.to_status == "done":
            day = event.at.date()
            completed_by_day[day] = completed_by_day.get(day, 0.0) + value_of(event.item_id)

    ideal_step = total / max(len(days) - 1, 1)
    remaining_points: list[dict[str, Any]] = []
    ideal_points: list[dict[str, Any]] = []
    scope_points: list[dict[str, Any]] = []
    remaining = total
    today = utcnow().date()
    for index, day in enumerate(days):
        remaining -= completed_by_day.get(day, 0.0)
        if day <= today:
            remaining_points.append({"x": day.isoformat(), "value": round(remaining, 2)})
        ideal_points.append({"x": day.isoformat(),
                             "value": round(max(total - ideal_step * index, 0.0), 2)})
        scope_points.append({"x": day.isoformat(), "value": total})

    return _chart(
        "burndown", f"Sprint burndown — {iteration.name}", unit,
        "Remaining selected unit by day against the ideal line. Scope changes are shown "
        "as a separate series. Units are never mixed in one chart.",
        series=[
            ChartSeries(key="remaining", label="Remaining", points=remaining_points),
            ChartSeries(key="ideal", label="Ideal", points=ideal_points),
            ChartSeries(key="scope", label="Committed scope", points=scope_points),
        ],
        warnings=[] if items else ["No items are assigned to this iteration."],
        filters={"iterationId": iteration_id, "unit": unit},
        insufficient_data=not items,
    )


async def velocity(project: Project, *, team: str = "default") -> ChartResponse:
    closed = await iterations.list({"projectId": project.id, "team": team,
                                    "state": "closed"}, sort=[("startDate", 1)])
    points: list[dict[str, Any]] = []
    for iteration in closed:
        items = await backlog_items.list({"projectId": project.id,
                                          "iterationId": iteration.id,
                                          "executionStatus": "done"})
        rows = await estimates.list({"projectId": project.id, "superseded": False,
                                     "itemId": {"$in": [i.id for i in items]}})
        points.append({"x": iteration.name,
                       "value": round(sum(e.story_points or 0.0 for e in rows), 2)})
    insufficient = len(points) < 3
    return _chart(
        "velocity", f"Velocity — team {team}", "story_points",
        "Completed story points per closed sprint for one team. Points from different "
        "teams are not comparable without a validated normalisation.",
        series=[ChartSeries(key="velocity", label="Completed points", points=points)],
        warnings=(["Fewer than three closed sprints: velocity is not yet meaningful."]
                  if insufficient else []),
        filters={"team": team}, insufficient_data=insufficient,
    )


async def cumulative_flow(project: Project, *, days: int = 30) -> ChartResponse:
    board = await boards.find_one({"projectId": project.id})
    columns = [c.key for c in board.columns] if board else [
        "backlog", "ready", "in_progress", "in_review", "done"]
    events = await status_events.list({"projectId": project.id}, sort=[("at", 1)])
    items = await backlog_items.list({"projectId": project.id})

    start = (utcnow() - timedelta(days=days)).date()
    series_points: dict[str, list[dict[str, Any]]] = {c: [] for c in columns}
    for offset in range(days + 1):
        day = start + timedelta(days=offset)
        snapshot: dict[str, int] = {c: 0 for c in columns}
        state_by_item: dict[str, str] = {i.id: "backlog" for i in items}
        for event in events:
            if event.at.date() <= day:
                state_by_item[event.item_id] = event.column or event.to_status
        for state in state_by_item.values():
            key = state if state in snapshot else columns[0]
            snapshot[key] += 1
        for column in columns:
            series_points[column].append({"x": day.isoformat(), "value": snapshot[column]})

    return _chart(
        "cumulative_flow", "Kanban cumulative flow", "items",
        "Item count per workflow column per day, derived from recorded status "
        "transitions. Widening bands indicate work in progress build up.",
        series=[ChartSeries(key=c, label=c.replace("_", " ").title(), points=p)
                for c, p in series_points.items()],
        filters={"days": days}, insufficient_data=not events,
    )


async def cycle_time(project: Project, *, use_working_time: bool = False) -> ChartResponse:
    events = await status_events.list({"projectId": project.id}, sort=[("at", 1)])
    started: dict[str, datetime] = {}
    finished: dict[str, datetime] = {}
    created: dict[str, datetime] = {}
    for event in events:
        if event.to_status in ("in_progress",) and event.item_id not in started:
            started[event.item_id] = event.at
        if event.to_status == "done":
            finished[event.item_id] = event.at
        created.setdefault(event.item_id, event.at)

    items = await backlog_items.list({"projectId": project.id})
    by_id = {i.id: i for i in items}
    points: list[dict[str, Any]] = []
    aging: list[dict[str, Any]] = []
    now = utcnow()
    for item_id, end in finished.items():
        begin = started.get(item_id)
        if not begin:
            continue
        hours = (end - begin).total_seconds() / 3600
        item = by_id.get(item_id)
        points.append({"x": end.date().isoformat(),
                       "value": round(hours / 24, 2),
                       "label": item.stable_id if item else item_id})
    for item_id, begin in started.items():
        if item_id in finished:
            continue
        item = by_id.get(item_id)
        aging.append({"x": item.stable_id if item else item_id,
                      "value": round((now - begin).total_seconds() / 86400, 2)})

    return _chart(
        "cycle_time", "Cycle time and work item aging", "days",
        "Cycle time starts when an item first enters In progress and ends when it is "
        "first marked Done. Aging shows items started but not finished. "
        f"Measured in {'working time' if use_working_time else 'calendar time'}.",
        series=[ChartSeries(key="cycle_time", label="Cycle time", points=points),
                ChartSeries(key="aging", label="Aging work in progress", points=aging)],
        filters={"workingTime": use_working_time},
        insufficient_data=len(points) < 3,
        warnings=(["Fewer than three completed items: distribution statistics are "
                   "not meaningful yet."] if len(points) < 3 else []),
    )


async def quality_and_scope(project: Project) -> ChartResponse:
    items = await backlog_items.list({"projectId": project.id})
    stories = [i for i in items if i.type == ItemType.STORY]
    approved = [i for i in items if i.approved_version is not None]
    pending = [i for i in items if i.approved_version is None or i.requires_reapproval]
    open_questions = await questions.count({"projectId": project.id, "status": "open"})
    critical_questions = await questions.count({"projectId": project.id, "status": "open",
                                                "severity": "critical"})
    open_findings = await findings.count({"projectId": project.id, "status": "open"})
    # Board work: stories and tasks, as on the Kanban board.
    work = [i for i in items if str(i.type) in {"story", "task"}]
    blocked = [i for i in work if str(i.execution_status) == "blocked"]
    started = [i for i in work
               if str(i.execution_status) in {"in_progress", "blocked", "in_review"}]
    tested_rows = await test_cases.aggregate([
        {"$match": {"projectId": project.id}},
        {"$group": {"_id": "$storyId"}},
    ])
    tested = len([r for r in tested_rows if r["_id"]])

    return _chart(
        "quality_scope", "Quality and scope", "count",
        "Counts of approved versus pending items, stories with at least one test, "
        "unresolved questions, open review findings, and board work that has started "
        "or is blocked, as of now.",
        categories=["items", "approved", "pending approval", "stories", "stories tested",
                    "open questions", "critical questions", "open findings",
                    "started", "blocked"],
        series=[ChartSeries(key="counts", label="Count", points=[
            {"category": "items", "value": len(items)},
            {"category": "approved", "value": len(approved)},
            {"category": "pending approval", "value": len(pending)},
            {"category": "stories", "value": len(stories)},
            {"category": "stories tested", "value": tested},
            {"category": "open questions", "value": open_questions},
            {"category": "critical questions", "value": critical_questions},
            {"category": "open findings", "value": open_findings},
            {"category": "started", "value": len(started)},
            {"category": "blocked", "value": len(blocked)},
        ])],
    )


async def milestone_schedule(project: Project) -> ChartResponse:
    rows = await milestones.list({"projectId": project.id}, sort=[("dueDate", 1)])
    return _chart(
        "milestones", "Milestones and dependencies", "date",
        "Baseline date versus current forecast date per milestone.",
        series=[
            ChartSeries(key="baseline", label="Baseline", points=[
                {"x": m.name, "value": (m.baseline_date or m.due_date).isoformat()}
                for m in rows]),
            ChartSeries(key="forecast", label="Forecast", points=[
                {"x": m.name, "value": (m.forecast_date or m.due_date).isoformat()}
                for m in rows]),
        ],
        insufficient_data=not rows,
    )


async def snapshot_daily(project: Project) -> dict[str, Any]:
    """Daily snapshot stored for historical charts (section 12)."""
    from app.models.planning import MetricSnapshot
    from app.repositories import metric_snapshots

    chart = await planned_vs_actual(project)
    values = {p["category"]: p["value"] for p in chart.series[0].points}
    snapshot = MetricSnapshot(project_id=project.id, as_of=utcnow(), kind="effort",
                              values=values,
                              methodology=chart.definition)
    await metric_snapshots.insert(snapshot)
    return values
