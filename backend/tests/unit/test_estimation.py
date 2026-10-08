"""Estimation, rollup and costing rules (section 11)."""
from __future__ import annotations

from datetime import date

from app.models.backlog import (EstimateCreate, EstimateMethod, RateCard,
                                RoleEffort)
from app.models.backlog import BacklogItemCreate
from app.models.common import ItemType
from app.repositories import rate_cards, worklogs
from app.services import backlog as backlog_service
from app.services.estimation import (actual_cost, capacity, cost_summary,
                                     effective_rate_card, estimate_cost,
                                     inconsistency_warnings, person_days,
                                     role_breakdown, rollup, save_estimate,
                                     total_hours)


async def _epic_with_children(project, actor_id, child_hours: list[float]):
    epic, _ = await backlog_service.create_item(project.id, BacklogItemCreate(
        type=ItemType.EPIC, title="Epic"), actor_id=actor_id)
    feature, _ = await backlog_service.create_item(project.id, BacklogItemCreate(
        type=ItemType.FEATURE, parent_id=epic.id, title="Feature"), actor_id=actor_id)
    stories = []
    for index, hours in enumerate(child_hours):
        story, _ = await backlog_service.create_item(project.id, BacklogItemCreate(
            type=ItemType.STORY, parent_id=feature.id, title=f"Story {index + 1}"),
            actor_id=actor_id)
        await save_estimate(project.id, story.id, EstimateCreate(
            method=EstimateMethod.EXPERT, story_points=3,
            role_efforts=[RoleEffort(role="engineering", hours=hours)],
            low_hours=hours * 0.8, high_hours=hours * 1.4), actor_id=actor_id)
        stories.append(story)
    return epic, feature, stories


async def test_parent_rough_estimate_is_kept_for_comparison_only(project, lead_user):
    """AT-12 — parent rough 100h versus a child rollup of 80h plus overhead."""
    epic, feature, _ = await _epic_with_children(project, lead_user.id, [30, 30, 20])

    await save_estimate(project.id, epic.id, EstimateCreate(
        method=EstimateMethod.ANALOGY, likely_hours=100,
        role_efforts=[RoleEffort(role="engineering", hours=100)],
        is_rough_parent=True), actor_id=lead_user.id)
    # Explicit parent level overhead, excluded from the child estimates.
    await save_estimate(project.id, epic.id, EstimateCreate(
        method=EstimateMethod.EXPERT, overhead_hours=12,
        role_efforts=[]), actor_id=lead_user.id)

    result = await rollup(project.id, epic.id, hours_per_person_day=8.0)

    assert result.children_hours == 80.0
    assert result.own_overhead_hours == 12.0
    assert result.detailed_hours == 92.0          # 80 children + 12 overhead
    assert result.rough_parent_hours == 100.0     # kept, never added
    assert result.person_days == 11.5
    assert any("kept for comparison" in w for w in result.warnings)


async def test_person_days_use_the_project_day_length():
    assert person_days(92.0, 8.0) == 11.5
    assert person_days(92.0, 7.5) == 12.27
    assert person_days(10.0, 0) == 0.0


async def test_total_effort_is_role_hours_plus_explicit_overhead(project, lead_user):
    story, _ = await backlog_service.create_item(project.id, BacklogItemCreate(
        type=ItemType.EPIC, title="Standalone"), actor_id=lead_user.id)
    estimate = await save_estimate(project.id, story.id, EstimateCreate(
        role_efforts=[RoleEffort(role="analysis", hours=4),
                      RoleEffort(role="engineering", hours=10),
                      RoleEffort(role="qa", hours=6)],
        overhead_hours=2.5), actor_id=lead_user.id)
    assert total_hours(estimate) == 22.5
    assert role_breakdown(estimate) == {"analysis": 4.0, "engineering": 10.0, "qa": 6.0}


async def test_estimated_cost_uses_role_rates_and_contingency():
    card = RateCard(name="Standard", currency="EUR", effective_from=date(2026, 1, 1),
                    rates={"engineering": "100.00", "qa": "80.00"},
                    contingency_percent=10.0)
    cost = estimate_cost({"engineering": 10.0, "qa": 5.0}, card)
    # (10 x 100) + (5 x 80) = 1400, plus 10 percent contingency
    assert cost.amount == "1540.00"
    assert cost.currency == "EUR"


async def test_points_and_effort_stay_independent_with_warnings(project, lead_user):
    item, _ = await backlog_service.create_item(project.id, BacklogItemCreate(
        type=ItemType.EPIC, title="Mismatch"), actor_id=lead_user.id)
    estimate = await save_estimate(project.id, item.id, EstimateCreate(
        story_points=8, role_efforts=[]), actor_id=lead_user.id)
    warnings = inconsistency_warnings(estimate)
    assert any("no role effort" in w for w in warnings)
    # The values are not forced into agreement.
    assert estimate.story_points == 8
    assert total_hours(estimate) == 0.0


async def test_actual_cost_uses_the_rate_effective_on_the_work_date(project, lead_user):
    from app.models.planning import Worklog

    await rate_cards.insert(RateCard(
        project_id=project.id, name="2025", currency="EUR",
        effective_from=date(2025, 1, 1), effective_to=date(2025, 12, 31),
        rates={"engineering": "90.00"}))
    await rate_cards.insert(RateCard(
        project_id=project.id, name="2026", currency="EUR",
        effective_from=date(2026, 1, 1), rates={"engineering": "100.00"}))

    await worklogs.insert(Worklog(project_id=project.id, user_id=lead_user.id,
                                  role="engineering", work_date=date(2025, 6, 1),
                                  hours=10, approved=True))
    await worklogs.insert(Worklog(project_id=project.id, user_id=lead_user.id,
                                  role="engineering", work_date=date(2026, 6, 1),
                                  hours=10, approved=True))
    # Unapproved entries are excluded from actual cost.
    await worklogs.insert(Worklog(project_id=project.id, user_id=lead_user.id,
                                  role="engineering", work_date=date(2026, 6, 2),
                                  hours=40, approved=False))

    cost = await actual_cost(project.id, currency="EUR")
    assert cost.amount == "1900.00"  # 10 x 90 + 10 x 100


async def test_capacity_does_not_apply_the_focus_factor_twice(project, lead_user):
    from app.models.project import WorkingCalendar

    start, end = date(2026, 3, 2), date(2026, 3, 6)  # one working week
    rows = await capacity(project.id, start, end, working_days=[1, 2, 3, 4, 5],
                          hours_per_person_day=8.0, holidays=[], focus_factor=0.8,
                          allocation_includes_focus=False)
    assert rows and rows[0].scheduled_hours == 40.0
    assert rows[0].available_hours == 32.0

    rows = await capacity(project.id, start, end, working_days=[1, 2, 3, 4, 5],
                          hours_per_person_day=8.0, holidays=[], focus_factor=0.8,
                          allocation_includes_focus=True)
    assert rows[0].focus_factor == 1.0
    assert rows[0].available_hours == 40.0


async def test_forecast_at_completion_is_actual_plus_remaining(project, lead_user):
    from app.models.planning import Worklog

    await rate_cards.insert(RateCard(
        project_id=project.id, name="Standard", currency="EUR",
        effective_from=date(2020, 1, 1), rates={"engineering": "100.00"}))
    await _epic_with_children(project, lead_user.id, [10, 10])
    await worklogs.insert(Worklog(project_id=project.id, user_id=lead_user.id,
                                  role="engineering", work_date=date(2026, 1, 5),
                                  hours=5, approved=True))

    summary = await cost_summary(project.id, currency="EUR", hours_per_person_day=8.0)
    assert summary.actual_cost.amount == "500.00"
    expected = (summary.actual_cost.value + summary.remaining_forecast.value)
    assert summary.forecast_at_completion.value == expected
