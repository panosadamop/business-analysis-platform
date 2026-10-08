"""Scrum, Kanban, capacity, time tracking and charts (section 12)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import ProjectContext, ProjectCtx, requires
from app.core.errors import ConflictState, Forbidden, NotFound, ValidationFailed
from app.core.policy import Permission
from app.core.utils import utcnow
from app.models.backlog import BacklogItemUpdate
from app.models.common import Base
from app.models.planning import (Allocation, AllocationCreate, CapacityRow,
                                 ChartResponse, CostSummary, Iteration,
                                 BOARD_LAYOUT_VERSION, IterationCreate,
                                 KanbanBoard, KanbanColumn,
                                 Milestone, MilestoneCreate, Worklog,
                                 WorklogCreate)
from app.repositories import (allocations, backlog_items, boards, iterations,
                              milestones, worklogs)
from app.services import audit, backlog as backlog_service, metrics
from app.services.estimation import (capacity, cost_summary,
                                     cross_project_allocation_warnings)

router = APIRouter(tags=["planning"], prefix="/projects/{project_id}")

DEFAULT_COLUMNS = [
    KanbanColumn(key="backlog", name="Backlog", maps_to_status="not_started",
                 is_start=True),
    KanbanColumn(key="ready", name="Ready", maps_to_status="ready"),
    KanbanColumn(key="in_progress", name="In progress", maps_to_status="in_progress",
                 wip_limit=5),
    KanbanColumn(key="blocked", name="Blocked", maps_to_status="blocked"),
    KanbanColumn(key="in_review", name="In review", maps_to_status="in_review",
                 wip_limit=3),
    KanbanColumn(key="done", name="Done", maps_to_status="done", is_done=True),
]


@router.get("/iterations", response_model=list[Iteration])
async def list_iterations(project_id: str, ctx: ProjectCtx) -> list[Iteration]:
    ctx.require(Permission.BACKLOG_READ)
    return await iterations.list({"projectId": project_id}, sort=[("startDate", 1)])


@router.post("/iterations", response_model=Iteration, status_code=201)
async def create_iteration(project_id: str, payload: IterationCreate,
                           ctx: ProjectContext = requires(Permission.PLANNING_MANAGE)
                           ) -> Iteration:
    iteration = Iteration(project_id=project_id, **payload.model_dump(by_alias=False))
    await iterations.insert(iteration)
    return iteration


@router.patch("/iterations/{iteration_id}", response_model=Iteration)
async def update_iteration(project_id: str, iteration_id: str, body: dict[str, Any],
                           ctx: ProjectContext = requires(Permission.PLANNING_MANAGE)
                           ) -> Iteration:
    allowed = {"name", "goal", "state", "capacityHours", "notes", "startDate", "endDate"}
    return await iterations.update(iteration_id,
                                   {k: v for k, v in body.items() if k in allowed},
                                   projectId=project_id)


@router.get("/board", response_model=KanbanBoard)
async def get_board(project_id: str, ctx: ProjectCtx) -> KanbanBoard:
    ctx.require(Permission.BACKLOG_READ)
    board = await boards.find_one({"projectId": project_id})
    if not board:
        board = KanbanBoard(project_id=project_id, columns=DEFAULT_COLUMNS,
                            layout_version=BOARD_LAYOUT_VERSION)
        await boards.insert(board)
    elif board.layout_version < BOARD_LAYOUT_VERSION:
        board = await _upgrade_board(board)
    return board


async def _upgrade_board(board: KanbanBoard) -> KanbanBoard:
    """Add the Blocked column to a board saved before it existed, once.

    It goes after the column holding work in progress. A board that already maps
    a column to the blocked status keeps its own. Recording the new layout
    version means a board that later removes Blocked is not given it back.
    """
    columns = list(board.columns)
    if not any(c.maps_to_status == "blocked" for c in columns):
        after = next((i for i, c in enumerate(columns) if c.maps_to_status == "in_progress"),
                     len(columns) - 1)
        columns.insert(after + 1, KanbanColumn(key="blocked", name="Blocked",
                                               maps_to_status="blocked"))
    return await boards.update(board.id, {
        "columns": [c.model_dump(by_alias=True) for c in columns],
        "layoutVersion": BOARD_LAYOUT_VERSION})


@router.put("/board", response_model=KanbanBoard)
async def update_board(project_id: str, body: dict[str, Any],
                       ctx: ProjectContext = requires(Permission.PLANNING_MANAGE)
                       ) -> KanbanBoard:
    board = await boards.find_one({"projectId": project_id})
    if not board:
        board = KanbanBoard(project_id=project_id, columns=DEFAULT_COLUMNS,
                            layout_version=BOARD_LAYOUT_VERSION)
        await boards.insert(board)
    return await boards.update(board.id, {"columns": body.get("columns", []),
                                          "layoutVersion": BOARD_LAYOUT_VERSION,
                                          "name": body.get("name", board.name)})


@router.get("/board/state")
async def board_state(project_id: str, ctx: ProjectCtx) -> dict[str, Any]:
    """Column contents with WIP limit evaluation."""
    ctx.require(Permission.BACKLOG_READ)
    board = await get_board(project_id, ctx)
    items = await backlog_items.list({"projectId": project_id,
                                      "type": {"$in": ["story", "task"]}},
                                     sort=[("order", 1)], limit=2000)
    columns: list[dict[str, Any]] = []
    for column in board.columns:
        members = [i for i in items
                   if (i.kanban_column or str(i.execution_status)) == column.key
                   or (i.kanban_column is None
                       and str(i.execution_status) == column.maps_to_status)]
        columns.append({
            "key": column.key, "name": column.name, "wipLimit": column.wip_limit,
            "mapsToStatus": column.maps_to_status,
            "count": len(members),
            # A limit of 0 means "nothing may sit here"; only None means no limit.
            "overLimit": column.wip_limit is not None and len(members) > column.wip_limit,
            "items": [{"id": i.id, "stableId": i.stable_id, "title": i.title,
                       "rev": i.rev, "executionStatus": str(i.execution_status),
                       "priority": str(i.priority), "ownerId": i.owner_id,
                       "blockedReason": i.blocked_reason,
                       "serviceClass": i.service_class,
                       "state": str(i.state),
                       "approvedVersion": i.approved_version}
                      for i in members],
        })
    return {"columns": columns,
            "note": "Execution status is tracked separately from artifact approval."}


class BoardMove(Base):
    item_id: str
    column_key: str
    #: The item revision the board showed; a stale move is refused, not applied.
    expected_rev: int | None = None
    #: Required when the column maps to the blocked status: what the work waits on.
    blocked_reason: str | None = None


@router.post("/board/move")
async def move_on_board(project_id: str, payload: BoardMove, ctx: ProjectCtx
                        ) -> dict[str, Any]:
    """Put a card in a column and set its execution status from that column.

    Execution status is delivery state only: moving a card never changes its
    approval. The change is recorded as a status event for cycle time and flow.
    A move that takes a column over its WIP limit is allowed and reported.
    Moving into a blocked column needs a reason; moving out of one clears it.
    """
    ctx.require_any(Permission.PLANNING_MANAGE, Permission.BACKLOG_EDIT)
    board = await get_board(project_id, ctx)
    column = next((c for c in board.columns if c.key == payload.column_key), None)
    if not column:
        raise NotFound(f"The board has no column '{payload.column_key}'")
    item = await backlog_items.find_one({"_id": payload.item_id, "projectId": project_id})
    if not item or str(item.type) not in {"story", "task"}:
        raise NotFound("No story or task with that id on this board")

    blocking = column.maps_to_status == "blocked"
    reason = (payload.blocked_reason or "").strip()
    if blocking and not reason:
        raise ValidationFailed("Say what the item is blocked by before moving it to "
                               f"{column.name}.", code="blocked_reason_required")
    updated, _ = await backlog_service.update_item(
        project_id, item.id,
        BacklogItemUpdate(kanban_column=column.key, execution_status=column.maps_to_status,
                          blocked_reason=reason if blocking else None,
                          expected_rev=payload.expected_rev),
        actor_id=ctx.user.id)

    state = await board_state(project_id, ctx)
    target = next(c for c in state["columns"] if c["key"] == column.key)
    warning = (f"{column.name} is over its WIP limit of {column.wip_limit}"
               if target["overLimit"] else None)
    return {"item": {"id": updated.id, "stableId": updated.stable_id, "rev": updated.rev,
                     "kanbanColumn": updated.kanban_column,
                     "executionStatus": str(updated.execution_status),
                     "blockedReason": updated.blocked_reason},
            "column": column.key, "warning": warning, "board": state}


@router.get("/milestones", response_model=list[Milestone])
async def list_milestones(project_id: str, ctx: ProjectCtx) -> list[Milestone]:
    ctx.require(Permission.BACKLOG_READ)
    return await milestones.list({"projectId": project_id}, sort=[("dueDate", 1)])


@router.post("/milestones", response_model=Milestone, status_code=201)
async def create_milestone(project_id: str, payload: MilestoneCreate,
                           ctx: ProjectContext = requires(Permission.PLANNING_MANAGE)
                           ) -> Milestone:
    milestone = Milestone(project_id=project_id, **payload.model_dump(by_alias=False))
    await milestones.insert(milestone)
    return milestone


@router.get("/allocations", response_model=list[Allocation])
async def list_allocations(project_id: str, ctx: ProjectCtx) -> list[Allocation]:
    ctx.require(Permission.BACKLOG_READ)
    return await allocations.list({"projectId": project_id}, sort=[("startDate", 1)])


@router.post("/allocations", response_model=dict, status_code=201)
async def create_allocation(project_id: str, payload: AllocationCreate,
                            ctx: ProjectContext = requires(Permission.PLANNING_MANAGE)
                            ) -> dict[str, Any]:
    allocation = Allocation(project_id=project_id, **payload.model_dump(by_alias=False))
    await allocations.insert(allocation)
    warnings = await cross_project_allocation_warnings([payload.user_id])
    return {"allocation": allocation.model_dump(by_alias=True), "warnings": warnings}


@router.get("/capacity", response_model=list[CapacityRow])
async def capacity_rows(project_id: str, ctx: ProjectCtx,
                        start: date | None = Query(None),
                        end: date | None = Query(None)) -> list[CapacityRow]:
    ctx.require(Permission.METRICS_READ)
    begin = start or utcnow().date()
    finish = end or begin + timedelta(days=27)
    calendar = ctx.project.calendar
    return await capacity(project_id, begin, finish,
                          working_days=calendar.working_days,
                          hours_per_person_day=calendar.hours_per_person_day,
                          holidays=calendar.holidays,
                          focus_factor=calendar.focus_factor,
                          allocation_includes_focus=calendar.allocation_includes_focus)


@router.get("/worklogs", response_model=list[Worklog])
async def list_worklogs(project_id: str, ctx: ProjectCtx,
                        item_id: str | None = Query(None),
                        approved: bool | None = Query(None)) -> list[Worklog]:
    ctx.require(Permission.METRICS_READ)
    query: dict[str, Any] = {"projectId": project_id}
    if item_id:
        query["itemId"] = item_id
    if approved is not None:
        query["approved"] = approved
    return await worklogs.list(query, sort=[("workDate", -1)], limit=2000)


@router.post("/worklogs", response_model=Worklog, status_code=201)
async def create_worklog(project_id: str, payload: WorklogCreate,
                         ctx: ProjectContext = requires(Permission.WORKLOG_WRITE)
                         ) -> Worklog:
    if payload.user_id and payload.user_id != ctx.user.id:
        ctx.require(Permission.WORKLOG_APPROVE)
    if payload.hours <= 0:
        raise ConflictState("Recorded time must be greater than zero")
    entry = Worklog(project_id=project_id, item_id=payload.item_id,
                    user_id=payload.user_id or ctx.user.id,
                    role=payload.role or (ctx.member.delivery_role if ctx.member else None),
                    work_date=payload.work_date, hours=payload.hours, note=payload.note)
    await worklogs.insert(entry)
    return entry


@router.post("/worklogs/{worklog_id}/approve", response_model=Worklog)
async def approve_worklog(project_id: str, worklog_id: str,
                          ctx: ProjectContext = requires(Permission.WORKLOG_APPROVE)
                          ) -> Worklog:
    entry = await worklogs.get(worklog_id, projectId=project_id)
    if not entry:
        raise NotFound("Time entry not found")
    updated = await worklogs.update(worklog_id, {"approved": True,
                                                 "approvedBy": ctx.user.id,
                                                 "approvedAt": utcnow()})
    await audit.record("worklog.approved", project_id=project_id, actor_id=ctx.user.id,
                       object_type="worklog", object_id=worklog_id,
                       detail={"hours": entry.hours, "workDate": str(entry.work_date)})
    return updated


@router.get("/cost-summary", response_model=CostSummary)
async def project_cost(project_id: str,
                       ctx: ProjectContext = requires(Permission.COST_READ)
                       ) -> CostSummary:
    return await cost_summary(project_id, currency=ctx.project.currency,
                              hours_per_person_day=ctx.project.calendar.hours_per_person_day)


@router.get("/charts/{chart}", response_model=ChartResponse)
async def chart(project_id: str, chart: str, ctx: ProjectCtx,
                iteration_id: str | None = Query(None),
                baseline_id: str | None = Query(None),
                unit: str = Query("story_points"),
                team: str = Query("default"),
                days: int = Query(30, le=180)) -> ChartResponse:
    ctx.require(Permission.METRICS_READ)
    project = ctx.project
    if chart == "planned_vs_actual":
        return await metrics.planned_vs_actual(project, baseline_id=baseline_id)
    if chart == "burndown":
        if not iteration_id:
            raise ConflictState("A burndown needs an iteration")
        return await metrics.burndown(project, iteration_id, unit=unit)
    if chart == "velocity":
        return await metrics.velocity(project, team=team)
    if chart == "cumulative_flow":
        return await metrics.cumulative_flow(project, days=days)
    if chart == "cycle_time":
        return await metrics.cycle_time(project)
    if chart == "quality_scope":
        return await metrics.quality_and_scope(project)
    if chart == "milestones":
        return await metrics.milestone_schedule(project)
    if chart == "cost":
        if not ctx.has(Permission.COST_READ):
            raise Forbidden("Cost charts require the cost.read permission")
        summary = await cost_summary(
            project.id, currency=project.currency,
            hours_per_person_day=project.calendar.hours_per_person_day)
        from app.models.planning import ChartSeries
        return ChartResponse(
            chart="cost", title="Cost and budget comparison", unit=project.currency,
            as_of=utcnow(), data_freshness="live query at request time",
            definition=("Baseline budget, actual cost from approved time entries at the "
                        "rate effective on the work date, and forecast at completion "
                        "(actual to date plus remaining forecast)."),
            categories=["estimated", "actual", "remaining", "forecast"],
            series=[ChartSeries(key="cost", label="Cost", points=[
                {"category": "estimated",
                 "value": float(summary.estimated_cost.amount) if summary.estimated_cost else 0},
                {"category": "actual",
                 "value": float(summary.actual_cost.amount) if summary.actual_cost else 0},
                {"category": "remaining",
                 "value": float(summary.remaining_forecast.amount)
                 if summary.remaining_forecast else 0},
                {"category": "forecast",
                 "value": float(summary.forecast_at_completion.amount)
                 if summary.forecast_at_completion else 0},
            ])],
            warnings=summary.warnings)
    raise NotFound(f"Unknown chart '{chart}'")
