"""Scrum, Kanban, capacity, worklogs and metrics (section 12)."""
from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import Field

from app.models.common import Base, Doc, Money


class IterationState(StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    CLOSED = "closed"


class Iteration(Doc):
    project_id: str
    name: str
    goal: str | None = None
    start_date: date
    end_date: date
    state: IterationState = IterationState.PLANNED
    team: str = "default"
    capacity_hours: float = 0.0
    committed_points: float = 0.0
    completed_points: float = 0.0
    notes: str | None = None


class KanbanColumn(Base):
    key: str
    name: str
    wip_limit: int | None = None
    #: Maps to the canonical execution status for metrics.
    maps_to_status: str = "in_progress"
    is_start: bool = False
    is_done: bool = False


#: Board layout revision. 2 added the Blocked column; boards saved before it
#: carry no value and read as 1, and are upgraded once when next opened.
BOARD_LAYOUT_VERSION = 2


class KanbanBoard(Doc):
    project_id: str
    name: str = "Delivery"
    layout_version: int = 1
    columns: list[KanbanColumn] = Field(default_factory=list)
    service_classes: list[str] = Field(default_factory=lambda: ["standard", "expedite",
                                                               "fixed_date", "intangible"])


class Allocation(Doc):
    project_id: str
    user_id: str
    role: str
    start_date: date
    end_date: date
    percent: float = 100.0
    note: str | None = None


class Leave(Doc):
    project_id: str | None = None
    user_id: str
    start_date: date
    end_date: date
    hours_per_day: float | None = None
    kind: str = "leave"


class Worklog(Doc):
    project_id: str
    item_id: str | None = None
    user_id: str
    role: str | None = None
    work_date: date
    hours: float
    note: str | None = None
    approved: bool = False
    approved_by: str | None = None
    approved_at: datetime | None = None
    corrected_from: str | None = None
    #: Origin and external id prevent duplicate actual effort on sync.
    origin: str = "internal"
    external_id: str | None = None


class Milestone(Doc):
    project_id: str
    name: str
    due_date: date
    baseline_date: date | None = None
    forecast_date: date | None = None
    status: str = "planned"
    depends_on: list[str] = Field(default_factory=list)
    note: str | None = None


class StatusEvent(Doc):
    project_id: str
    item_id: str
    from_status: str | None = None
    to_status: str
    at: datetime
    actor_id: str | None = None
    origin: str = "internal"
    column: str | None = None


class MetricSnapshot(Doc):
    """Daily snapshot; charts expose as-of time and data freshness."""

    project_id: str
    as_of: datetime
    kind: str
    values: dict = Field(default_factory=dict)
    methodology: str | None = None
    baseline_id: str | None = None


class CapacityRow(Base):
    user_id: str
    display_name: str
    role: str | None = None
    period_start: date
    period_end: date
    scheduled_hours: float = 0.0
    leave_hours: float = 0.0
    allocation_percent: float = 100.0
    focus_factor: float = 1.0
    available_hours: float = 0.0
    planned_hours: float = 0.0
    overloaded: bool = False


class ChartSeries(Base):
    key: str
    label: str
    points: list[dict] = Field(default_factory=list)


class ChartResponse(Base):
    """Every chart carries its definition, units, filters and freshness."""

    chart: str
    title: str
    unit: str
    as_of: datetime
    data_freshness: str
    definition: str
    series: list[ChartSeries] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    insufficient_data: bool = False
    filters: dict = Field(default_factory=dict)


class IterationCreate(Base):
    name: str
    goal: str | None = None
    start_date: date
    end_date: date
    team: str = "default"
    capacity_hours: float = 0.0


class WorklogCreate(Base):
    item_id: str | None = None
    user_id: str | None = None
    role: str | None = None
    work_date: date
    hours: float
    note: str | None = None


class AllocationCreate(Base):
    user_id: str
    role: str
    start_date: date
    end_date: date
    percent: float = 100.0


class MilestoneCreate(Base):
    name: str
    due_date: date
    baseline_date: date | None = None
    forecast_date: date | None = None
    depends_on: list[str] = Field(default_factory=list)
    note: str | None = None


class CostSummary(Base):
    currency: str = "EUR"
    baseline_budget: Money | None = None
    estimated_cost: Money | None = None
    actual_cost: Money | None = None
    forecast_at_completion: Money | None = None
    remaining_forecast: Money | None = None
    warnings: list[str] = Field(default_factory=list)
