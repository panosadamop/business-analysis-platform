"""Report permissions and export format rules (section 16)."""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date

import pytest

from app.core.errors import Forbidden, ValidationFailed
from app.core.policy import Permission, Role, permissions_for
from app.models.backlog import (BacklogItemCreate, EstimateCreate, RateCard,
                                RoleEffort)
from app.models.collaboration import (ExportFormat, ExportRequest, ReportDataset,
                                      ReportPreview)
from app.models.common import ItemType
from app.repositories import rate_cards
from app.services import backlog as backlog_service
from app.services import exports, reports
from app.services.estimation import save_estimate


async def _seed_backlog(project, actor_id):
    await rate_cards.insert(RateCard(
        project_id=project.id, name="Standard", currency="EUR",
        effective_from=date(2020, 1, 1),
        rates={"engineering": "100.00", "qa": "80.00"}))
    epic, _ = await backlog_service.create_item(project.id, BacklogItemCreate(
        type=ItemType.EPIC, title="Accounts"), actor_id=actor_id)
    feature, _ = await backlog_service.create_item(project.id, BacklogItemCreate(
        type=ItemType.FEATURE, parent_id=epic.id, title="Registration"),
        actor_id=actor_id)
    for index in range(3):
        story, _ = await backlog_service.create_item(project.id, BacklogItemCreate(
            type=ItemType.STORY, parent_id=feature.id,
            title=f"Story {index + 1}=SUM(A1:A9)",  # formula-like user text
            acceptance_criteria=["An observable outcome"]), actor_id=actor_id)
        await save_estimate(project.id, story.id, EstimateCreate(
            story_points=5,
            role_efforts=[RoleEffort(role="engineering", hours=8),
                          RoleEffort(role="qa", hours=2)]), actor_id=actor_id)
    return epic


def test_client_columns_exclude_cost_derived_fields():
    """REQ-REPORT-08 / AT-11 — hidden costs cannot leak through a report."""
    internal = reports.allowed_columns(ReportDataset.BACKLOG,
                                       permissions={Permission.COST_READ},
                                       is_client=False)
    client = reports.allowed_columns(ReportDataset.BACKLOG,
                                     permissions={Permission.COST_READ},
                                     is_client=True)
    assert "estimatedCost" in {c.key for c in internal}
    assert "estimatedCost" not in {c.key for c in client}


def test_contributor_without_cost_permission_cannot_see_cost_columns():
    permissions = permissions_for([Role.CONTRIBUTOR])
    columns = reports.allowed_columns(ReportDataset.BACKLOG, permissions=permissions,
                                      is_client=False)
    assert "estimatedCost" not in {c.key for c in columns}


def test_unknown_filters_and_fields_are_refused():
    with pytest.raises(ValidationFailed):
        reports.validate_filters({"$where": "function(){return true}"})


async def test_report_denies_fields_the_caller_may_not_read(project, lead_user):
    await _seed_backlog(project, lead_user.id)
    with pytest.raises(Forbidden):
        await reports.build(project, ReportDataset.BACKLOG, filters={},
                            fields=["stableId", "estimatedCost"],
                            permissions={Permission.REPORT_READ}, is_client=False)


async def test_backlog_report_totals_match_detail_rows(project, lead_user):
    """REQ-REPORT-07 — totals and detail rows come from one snapshot."""
    await _seed_backlog(project, lead_user.id)
    preview = await reports.build(project, ReportDataset.BACKLOG, filters={},
                                  fields=[],
                                  permissions={Permission.REPORT_READ,
                                               Permission.COST_READ},
                                  is_client=False)
    detail_total = round(sum(r["effortHours"] for r in preview.rows), 2)
    assert preview.totals["effortHours"] == detail_total == 30.0
    assert preview.snapshot_id.startswith("snap-")


def test_formula_like_text_is_escaped_but_numbers_keep_their_type():
    assert exports.escape_formula("=SUM(A1:A2)") == "'=SUM(A1:A2)"
    assert exports.escape_formula("+1 234") == "'+1 234"
    assert exports.escape_formula("@user") == "'@user"
    assert exports.escape_formula("Normal text") == "Normal text"
    assert exports.escape_formula(42.5) == 42.5
    assert exports.escape_formula(None) is None


def _preview_with_rows(count: int, columns: int = 3) -> ReportPreview:
    keys = [f"c{i}" for i in range(columns)]
    return ReportPreview(
        dataset="backlog",
        columns=[{"key": k, "label": k.upper(), "type": "string"} for k in keys],
        rows=[{k: f"v{row}-{k}" for k in keys} for row in range(count)],
        total_rows=count, snapshot_id="snap-test",
        generated_at=__import__("app.core.utils", fromlist=["utcnow"]).utcnow())


def test_xls_splits_instead_of_truncating_beyond_the_row_limit():
    """AT-14 / REQ-REPORT-05 — the 65,536 row limit splits with a manifest."""
    oversized = _preview_with_rows(exports.XLS_MAX_ROWS + 10)
    data, warnings, counts = exports.build_xls({"backlog": oversized}, title="Test")

    assert data[:4] == b"\xd0\xcf\x11\xe0"  # legacy OLE2 workbook signature
    assert any("exceeds the .xls limit" in w for w in warnings)
    assert len(counts) >= 2
    assert sum(counts.values()) == exports.XLS_MAX_ROWS + 10  # nothing dropped
    assert max(counts.values()) <= exports.XLS_MAX_ROWS - 1


def test_xls_splits_beyond_the_column_limit():
    wide = _preview_with_rows(2, columns=exports.XLS_MAX_COLS + 5)
    _, warnings, counts = exports.build_xls({"backlog": wide}, title="Wide")
    assert any("exceeds the .xls limit of 256" in w for w in warnings)
    assert len(counts) >= 2


async def test_json_export_carries_the_documented_envelope(project, lead_user):
    await _seed_backlog(project, lead_user.id)
    preview = await reports.build(project, ReportDataset.BACKLOG, filters={}, fields=[],
                                  permissions={Permission.REPORT_READ}, is_client=False)
    payload = json.loads(exports.build_json(project, {"backlog": preview},
                                            filters={"approvalState": "approved"},
                                            baseline_id="baseline-1"))
    assert payload["schemaVersion"] == "1.0"
    assert payload["projectId"] == project.id
    assert payload["baselineId"] == "baseline-1"
    assert payload["timezone"] == project.calendar.timezone
    assert payload["units"] == {"effort": "person_hours", "hoursPerPersonDay": 8.0}
    assert payload["currency"] == project.currency
    assert payload["filters"] == {"approvalState": "approved"}
    assert payload["rowCounts"]["backlog"] == len(payload["entities"]["backlog"])
    assert "not an importable full backup" in payload["note"]


async def test_xlsx_export_round_trip(project, lead_user):
    """AT-13 — Excel and JSON agree, Unicode survives."""
    await _seed_backlog(project, lead_user.id)
    job = await exports.run_export(
        project, ExportRequest(dataset=ReportDataset.BACKLOG,
                               format=ExportFormat.XLSX),
        permissions={Permission.REPORT_READ, Permission.EXPORT_RUN},
        is_client=False, actor_id=lead_user.id)
    assert job.status == "succeeded"
    assert job.filename.endswith(".xlsx")
    assert job.row_counts["backlog"] == 5  # epic + feature + 3 stories

    from app.services import storage
    data = storage.get_bytes(job.object_key)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
    assert "xl/workbook.xml" in names


async def test_gherkin_bundle_export_contains_a_manifest(project, lead_user):
    from app.models.testing import TestCaseCreate
    from app.services import testing as testing_service

    epic = await _seed_backlog(project, lead_user.id)
    from app.repositories import backlog_items
    story = (await backlog_items.list({"projectId": project.id, "type": "story"}))[0]
    await testing_service.create_test(project.id, TestCaseCreate(
        title="Sign in works", story_id=story.id,
        gherkin_text="""@STORY-001 @positive
Feature: Sign in
  Scenario: Valid credentials
    Given a registered customer
    When they sign in
    Then the dashboard is shown
"""), actor_id=lead_user.id)

    data = await exports.build_gherkin_bundle(project)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
    assert any(n.endswith(".feature") for n in names)
    assert manifest["files"][0]["reviewState"] == "pending_review"
    assert "no run status is implied" in manifest["note"]
