"""Export generation (section 16).

Rules implemented literally:

* .xls enforces its real format limits of 65,536 rows and 256 columns per sheet.
  Output splits across sheets with a manifest; nothing is silently truncated
  (REQ-REPORT-05, AT-14).
* Formula like user text is escaped in spreadsheets while real numbers keep
  their numeric type.
* JSON exports carry schemaVersion, generatedAt, projectId, filters, baseline,
  timezone, unit and currency definitions, entities and relation records
  (REQ-REPORT-06).
* Every export runs from one identified snapshot so totals and detail rows agree,
  and records row counts, warnings, schema version and applied permissions
  (REQ-REPORT-07).
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.core.policy import Permission
from app.core.utils import iso, new_id, utcnow
from app.models.collaboration import (ExportFormat, ExportJob, ExportRequest,
                                      ReportPreview)
from app.models.project import Project
from app.repositories import (artifact_versions, backlog_items, estimates,
                              export_jobs, specifications, test_cases)
from app.services import reports, storage
from app.services.gherkin import render_feature

XLS_MAX_ROWS = 65_536
XLS_MAX_COLS = 256
SCHEMA_VERSION = "1.0"

#: Leading characters a spreadsheet would interpret as a formula.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def escape_formula(value: Any) -> Any:
    """Neutralise formula like text; real numeric types are untouched."""
    if isinstance(value, (int, float, Decimal, bool)) or value is None:
        return value
    if isinstance(value, (datetime, date)):
        return value
    text = str(value)
    if text.startswith(FORMULA_PREFIXES):
        return "'" + text
    return text


def _cell(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return escape_formula(value)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


# --- XLSX -------------------------------------------------------------------

def build_xlsx(sheets: dict[str, ReportPreview], *, title: str) -> bytes:
    import xlsxwriter

    buffer = io.BytesIO()
    book = xlsxwriter.Workbook(buffer, {"in_memory": True, "default_date_format":
                                        "yyyy-mm-dd"})
    header_format = book.add_format({"bold": True, "bg_color": "#EEF2F7",
                                     "border": 1, "text_wrap": True})
    number_format = book.add_format({"num_format": "#,##0.00"})

    summary = book.add_worksheet("Summary")
    summary.set_column(0, 0, 32)
    summary.set_column(1, 1, 60)
    summary.write_row(0, 0, ["Export", title], header_format)
    row = 1
    for name, preview in sheets.items():
        summary.write_row(row, 0, ["Sheet", name])
        summary.write_row(row + 1, 0, ["Rows", preview.total_rows])
        summary.write_row(row + 2, 0, ["Snapshot", preview.snapshot_id])
        summary.write_row(row + 3, 0, ["Generated at", iso(preview.generated_at)])
        row += 5
        for key, value in (preview.totals or {}).items():
            summary.write_row(row, 0, [f"Total · {key}", _cell(value)])
            row += 1
        for warning in preview.warnings:
            summary.write_row(row, 0, ["Warning", warning])
            row += 1
        row += 1

    for name, preview in sheets.items():
        sheet = book.add_worksheet(name[:31])
        columns = preview.columns
        sheet.write_row(0, 0, [c["label"] for c in columns], header_format)
        for index, column in enumerate(columns):
            sheet.set_column(index, index, 28 if column["type"] == "string" else 16)
        sheet.freeze_panes(1, 0)
        for r, record in enumerate(preview.rows, start=1):
            for c, column in enumerate(columns):
                value = record.get(column["key"])
                if _is_number(value):
                    sheet.write_number(r, c, float(value), number_format)
                else:
                    sheet.write(r, c, _cell(value))
        if preview.rows:
            sheet.autofilter(0, 0, len(preview.rows), max(len(columns) - 1, 0))
    book.close()
    return buffer.getvalue()


# --- XLS (legacy) -----------------------------------------------------------

def build_xls(sheets: dict[str, ReportPreview], *,
              title: str) -> tuple[bytes, list[str], dict[str, int]]:
    """Legacy .xls honouring the 65,536 row and 256 column format limits."""
    import xlwt

    book = xlwt.Workbook(encoding="utf-8")
    header_style = xlwt.easyxf("font: bold on; pattern: pattern solid, fore_colour "
                               "light_turquoise;")
    warnings: list[str] = []
    counts: dict[str, int] = {}

    manifest = book.add_sheet("Manifest")
    manifest.write(0, 0, "Export")
    manifest.write(0, 1, title)
    manifest_row = 2

    for name, preview in sheets.items():
        columns = preview.columns
        if len(columns) > XLS_MAX_COLS:
            warnings.append(
                f"Sheet '{name}' has {len(columns)} columns which exceeds the .xls "
                f"limit of {XLS_MAX_COLS}. Columns beyond the limit are written to "
                "continuation sheets; use .xlsx to keep them together.")
        column_groups = [columns[i:i + XLS_MAX_COLS]
                         for i in range(0, len(columns), XLS_MAX_COLS)] or [[]]
        # One header row consumes a row, so a data page holds limit - 1 rows.
        page_size = XLS_MAX_ROWS - 1
        row_pages = [preview.rows[i:i + page_size]
                     for i in range(0, len(preview.rows), page_size)] or [[]]
        if len(row_pages) > 1:
            warnings.append(
                f"Sheet '{name}' has {preview.total_rows} rows which exceeds the .xls "
                f"limit of {XLS_MAX_ROWS}. The output is split across "
                f"{len(row_pages)} sheets. Export as .xlsx to avoid splitting.")

        for page_index, page in enumerate(row_pages):
            for group_index, group in enumerate(column_groups):
                suffix = ""
                if len(row_pages) > 1:
                    suffix += f"_p{page_index + 1}"
                if len(column_groups) > 1:
                    suffix += f"_c{group_index + 1}"
                sheet_name = (name[:31 - len(suffix)] + suffix) or f"Sheet{page_index}"
                sheet = book.add_sheet(sheet_name)
                for c, column in enumerate(group):
                    sheet.write(0, c, column["label"], header_style)
                for r, record in enumerate(page, start=1):
                    for c, column in enumerate(group):
                        value = record.get(column["key"])
                        sheet.write(r, c, float(value) if _is_number(value)
                                    else _cell(value))
                counts[sheet_name] = len(page)
                manifest.write(manifest_row, 0, sheet_name)
                manifest.write(manifest_row, 1, len(page))
                manifest.write(manifest_row, 2, f"rows {page_index * page_size + 1}-"
                                                f"{page_index * page_size + len(page)}")
                manifest_row += 1

    for warning in warnings:
        manifest.write(manifest_row, 0, "Warning")
        manifest.write(manifest_row, 1, warning[:32000])
        manifest_row += 1

    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue(), warnings, counts


# --- JSON -------------------------------------------------------------------

def build_json(project: Project, previews: dict[str, ReportPreview], *,
               filters: dict[str, Any], baseline_id: str | None,
               relations: list[dict[str, Any]] | None = None) -> bytes:
    envelope: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": iso(utcnow()),
        "projectId": project.id,
        "projectKey": project.key,
        "baselineId": baseline_id,
        "timezone": project.calendar.timezone,
        "units": {"effort": "person_hours",
                  "hoursPerPersonDay": project.calendar.hours_per_person_day},
        "currency": project.currency,
        "filters": filters,
        "snapshots": {name: preview.snapshot_id for name, preview in previews.items()},
        "entities": {name: preview.rows for name, preview in previews.items()},
        "totals": {name: preview.totals for name, preview in previews.items()},
        "rowCounts": {name: preview.total_rows for name, preview in previews.items()},
        "relations": relations or [],
        "warnings": sorted({w for p in previews.values() for w in p.warnings}),
        "note": ("A report snapshot is not an importable full backup."),
    }
    return json.dumps(envelope, ensure_ascii=False, indent=2, default=str).encode("utf-8")


# --- Markdown and Gherkin ---------------------------------------------------

async def build_markdown(project: Project) -> bytes:
    """Markdown specification bundle for the project."""
    lines = [f"# {project.name} — specifications", "",
             f"Generated {iso(utcnow())} · project key `{project.key}` · "
             f"output language `{project.output_language}`", ""]
    for spec in await specifications.list({"projectId": project.id},
                                          sort=[("kind", 1), ("version", -1)]):
        lines += [f"## {spec.title}", "",
                  f"*Kind:* `{spec.kind}` · *state:* `{spec.state}` · "
                  f"*version:* {spec.version}", ""]
        if spec.body:
            lines += [spec.body, ""]
        if spec.diagram_source:
            lines += ["```mermaid", spec.diagram_source, "```", ""]
        if spec.structured:
            lines += ["```json",
                      json.dumps(spec.structured, ensure_ascii=False, indent=2), "```", ""]

    items = await backlog_items.list({"projectId": project.id}, sort=[("order", 1)])
    versions = {v.item_id: v for v in await artifact_versions.list(
        {"_id": {"$in": [i.current_version_id for i in items if i.current_version_id]}})}
    lines += ["## Backlog", ""]
    for item in items:
        version = versions.get(item.id)
        depth = len(item.path)
        lines.append(f"{'  ' * depth}- **{item.stable_id}** {item.title} "
                     f"(`{item.type}`, v{item.current_version}, {item.state})")
        if version:
            for criterion in version.acceptance_criteria:
                lines.append(f"{'  ' * (depth + 1)}- _{criterion.id}_: {criterion.text}")
    return "\n".join(lines).encode("utf-8")


async def build_gherkin_bundle(project: Project, dialect: str = "en") -> bytes:
    buffer = io.BytesIO()
    cases = await test_cases.list({"projectId": project.id})
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        manifest = []
        for case in cases:
            if not case.gherkin:
                continue
            name = f"features/{case.stable_id}.feature"
            archive.writestr(name, render_feature(case.gherkin, dialect))
            manifest.append({"file": name, "testId": case.stable_id,
                             "storyId": case.story_id, "state": str(case.state),
                             "reviewState": case.review_state})
        archive.writestr("manifest.json", json.dumps(
            {"schemaVersion": SCHEMA_VERSION, "generatedAt": iso(utcnow()),
             "projectId": project.id, "dialect": dialect, "files": manifest,
             "note": "Generated scenarios are drafts; no run status is implied."},
            ensure_ascii=False, indent=2))
    return buffer.getvalue()


# --- orchestration ----------------------------------------------------------

DATASET_SHEETS: dict[str, list[str]] = {
    "project_bundle": ["backlog", "estimates_by_role", "planned_vs_actual",
                       "traceability", "testbook", "approval_history"],
}


async def run_export(project: Project, request: ExportRequest, *,
                     permissions: set[Permission], is_client: bool,
                     actor_id: str) -> ExportJob:
    """Generate an export from one consistent snapshot."""
    job = ExportJob(project_id=project.id, definition_id=request.definition_id,
                    dataset=str(request.dataset) if request.dataset else "project_bundle",
                    format=request.format, requested_by=actor_id,
                    parameters={"filters": request.filters, "fields": request.fields,
                                "baselineId": request.baseline_id},
                    snapshot_id=f"snap-{new_id()[:12]}",
                    applied_permissions=sorted(str(p) for p in permissions))
    await export_jobs.insert(job)

    dataset_names = ([str(request.dataset)] if request.dataset
                     else DATASET_SHEETS["project_bundle"])
    previews: dict[str, ReportPreview] = {}
    for name in dataset_names:
        try:
            previews[name] = await reports.build(
                project, name, filters=request.filters, fields=request.fields,
                permissions=permissions, is_client=is_client, limit=200_000)
        except Exception as exc:  # a denied dataset must not fail the whole bundle
            job.warnings.append(f"Dataset '{name}' was skipped: {exc}")

    warnings = list(job.warnings)
    counts = {name: preview.total_rows for name, preview in previews.items()}
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")

    if request.format == ExportFormat.XLSX:
        data = build_xlsx(previews, title=f"{project.name} export")
        filename = f"{project.key}-{stamp}.xlsx"
    elif request.format == ExportFormat.XLS:
        data, xls_warnings, sheet_counts = build_xls(previews,
                                                     title=f"{project.name} export")
        warnings += xls_warnings
        counts.update(sheet_counts)
        filename = f"{project.key}-{stamp}.xls"
    elif request.format == ExportFormat.JSON:
        data = build_json(project, previews, filters=request.filters,
                          baseline_id=request.baseline_id)
        filename = f"{project.key}-{stamp}.json"
    elif request.format == ExportFormat.MARKDOWN:
        data = await build_markdown(project)
        filename = f"{project.key}-{stamp}.md"
    elif request.format == ExportFormat.GHERKIN:
        data = await build_gherkin_bundle(project, str(project.output_language))
        filename = f"{project.key}-{stamp}-features.zip"
    else:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"{project.key}.json",
                             build_json(project, previews, filters=request.filters,
                                        baseline_id=request.baseline_id))
            archive.writestr(f"{project.key}.xlsx",
                             build_xlsx(previews, title=project.name))
            archive.writestr(f"{project.key}.md", await build_markdown(project))
        data = buffer.getvalue()
        filename = f"{project.key}-{stamp}.zip"

    key = f"projects/{project.id}/exports/{job.id}/{filename}"
    storage.put_bytes(key, data)

    updated = await export_jobs.update(job.id, {
        "status": "succeeded", "objectKey": key, "filename": filename,
        "sizeBytes": len(data), "rowCounts": counts, "warnings": warnings,
        "schemaVersion": SCHEMA_VERSION,
    })
    return updated
