"""Test case maintenance, coverage matrix and testbook assembly (section 13)."""
from __future__ import annotations

from typing import Any

from app.core.errors import ConflictState, NotFound, ValidationFailed
from app.core.utils import utcnow
from app.models.common import ArtifactState, ItemType, Priority
from app.models.testing import (CoverageMatrix, CoverageRow, TestCase,
                                TestCaseCreate, TestCaseUpdate, Testbook,
                                TestStep, TestType, TestVersion)
from app.repositories import (artifact_versions, backlog_items, test_cases,
                              test_versions, testbooks)
from app.services import audit, gherkin as gherkin_service


async def create_test(project_id: str, payload: TestCaseCreate, *,
                      actor_id: str) -> TestCase:
    index = await test_cases.count({"projectId": project_id}) + 1
    feature = None
    validation: dict[str, Any] = {}
    if payload.gherkin_text:
        result = gherkin_service.validate(payload.gherkin_text)
        validation = result.model_dump(by_alias=True)
        if not result.valid:
            raise ValidationFailed("The Gherkin document is not valid",
                                   details={"errors": result.errors})
        feature = gherkin_service.feature_from_text(payload.gherkin_text)

    story = await backlog_items.get(payload.story_id, projectId=project_id) \
        if payload.story_id else None
    case = TestCase(
        project_id=project_id, stable_id=f"TC-{index:03d}", title=payload.title,
        objective=payload.objective, story_id=payload.story_id,
        story_version=story.current_version if story else None,
        criterion_ids=payload.criterion_ids, test_type=TestType(payload.test_type),
        priority=Priority(payload.priority), preconditions=payload.preconditions,
        steps=payload.steps, expected_results=payload.expected_results,
        gherkin=feature, tags=payload.tags, validation=validation,
        owner_subtree_root=story.path[0] if story and story.path else payload.story_id,
    )
    await test_cases.insert(case)
    await audit.record("test.created", project_id=project_id, actor_id=actor_id,
                       object_type="testCase", object_id=case.id,
                       detail={"stableId": case.stable_id})
    return case


async def update_test(project_id: str, test_id: str, payload: TestCaseUpdate, *,
                      actor_id: str) -> TestCase:
    case = await test_cases.get(test_id, projectId=project_id)
    if not case:
        raise NotFound("Test case not found")
    if payload.expected_rev is not None and payload.expected_rev != case.rev:
        raise ConflictState("The test case changed while you were editing it",
                            details={"currentRev": case.rev})

    # Approved tests are immutable; editing creates the next draft version.
    if case.state == ArtifactState.APPROVED:
        await test_versions.insert(TestVersion(
            project_id=project_id, test_case_id=case.id, version=case.version,
            snapshot=case.model_dump(by_alias=True), state=case.state,
            author_id=actor_id))

    changes: dict[str, Any] = {}
    data = payload.model_dump(exclude_unset=True, by_alias=False)
    for field in ("title", "objective", "criterion_ids", "test_type", "priority",
                  "preconditions", "expected_results", "environment_assumptions",
                  "tags", "review_state"):
        if data.get(field) is not None:
            changes[_camel(field)] = data[field]
    if data.get("steps") is not None:
        changes["steps"] = [s.model_dump(by_alias=True) if isinstance(s, TestStep) else s
                            for s in data["steps"]]
    if data.get("gherkin_text"):
        result = gherkin_service.validate(data["gherkin_text"])
        if not result.valid:
            raise ValidationFailed("The Gherkin document is not valid",
                                   details={"errors": result.errors})
        feature = gherkin_service.feature_from_text(data["gherkin_text"])
        changes["gherkin"] = feature.model_dump(by_alias=True) if feature else None
        changes["validation"] = result.model_dump(by_alias=True)

    if case.state == ArtifactState.APPROVED:
        changes["version"] = case.version + 1
        changes["state"] = str(ArtifactState.DRAFT)
        changes["reviewState"] = "pending_review"
    updated = await test_cases.update(test_id, changes, projectId=project_id)
    await audit.record("test.updated", project_id=project_id, actor_id=actor_id,
                       object_type="testCase", object_id=test_id,
                       object_version=updated.version)
    return updated


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(p.title() for p in rest)


async def coverage(project_id: str, *, root_id: str | None = None) -> CoverageMatrix:
    """Flags criteria with no tests and tests with no linked requirement."""
    query: dict[str, Any] = {"projectId": project_id}
    if root_id:
        query["$or"] = [{"_id": root_id}, {"path": root_id}]
    items = await backlog_items.list(query)
    item_ids = [i.id for i in items]
    versions = await artifact_versions.list(
        {"_id": {"$in": [i.current_version_id for i in items if i.current_version_id]}})
    by_item = {v.item_id: v for v in versions}
    cases = await test_cases.list({"projectId": project_id})

    tests_by_criterion: dict[str, list[str]] = {}
    for case in cases:
        for criterion_id in case.criterion_ids:
            tests_by_criterion.setdefault(criterion_id, []).append(case.stable_id)

    rows: list[CoverageRow] = []
    for item in items:
        version = by_item.get(item.id)
        if not version:
            continue
        for criterion in version.acceptance_criteria:
            test_ids = tests_by_criterion.get(criterion.id, [])
            rows.append(CoverageRow(
                criterion_id=criterion.id, criterion_text=criterion.text,
                item_id=item.id, item_stable_id=item.stable_id, item_title=item.title,
                test_ids=test_ids, covered=bool(test_ids)))

    unlinked = [
        {"testId": c.id, "stableId": c.stable_id, "title": c.title,
         "reason": "No acceptance criterion or requirement is linked"}
        for c in cases
        if not c.criterion_ids and not c.requirement_ids
        and (not item_ids or c.story_id in item_ids or c.story_id is None)
    ]
    covered = sum(1 for r in rows if r.covered)
    return CoverageMatrix(
        rows=rows, uncovered_criteria=len(rows) - covered, unlinked_tests=unlinked,
        covered_percent=round(covered / len(rows) * 100, 1) if rows else 0.0,
        total_criteria=len(rows), total_tests=len(cases),
    )


async def assemble_testbook(project_id: str, *, name: str, release_scope: str | None,
                            actor_id: str) -> Testbook:
    """Versioned test plan with manifest, suites, coverage and unresolved gaps."""
    matrix = await coverage(project_id)
    cases = await test_cases.list({"projectId": project_id})
    items = await backlog_items.list({"projectId": project_id})
    by_id = {i.id: i for i in items}

    suites: dict[str, dict[str, Any]] = {}
    for case in cases:
        story = by_id.get(case.story_id or "")
        parent = by_id.get(story.parent_id or "") if story else None
        suite_key = parent.stable_id if parent else "cross-story"
        suite = suites.setdefault(suite_key, {
            "key": suite_key,
            "name": parent.title if parent else "Cross story and end to end",
            "cases": [],
        })
        suite["cases"].append({
            "stableId": case.stable_id, "title": case.title,
            "type": str(case.test_type), "priority": str(case.priority),
            "storyStableId": story.stable_id if story else None,
            "criterionIds": case.criterion_ids,
            "state": str(case.state), "reviewState": case.review_state,
            "gherkin": gherkin_service.render_feature(case.gherkin) if case.gherkin else None,
        })

    previous = await testbooks.list({"projectId": project_id}, sort=[("version", -1)], limit=1)
    version = (previous[0].version + 1) if previous else 1

    book = Testbook(
        project_id=project_id, name=name, version=version,
        purpose=("Versioned test plan covering the approved and draft scope of the "
                 "project. Generation never records a run status."),
        release_scope=release_scope,
        manifest=[{"itemId": i.id, "stableId": i.stable_id, "type": str(i.type),
                   "version": i.current_version, "approvedVersion": i.approved_version}
                  for i in items if i.type in (ItemType.EPIC, ItemType.FEATURE,
                                               ItemType.STORY)],
        assumptions=["Tests are drafts awaiting review.",
                     "Synthetic data only; no production content is referenced."],
        environments=[{"name": "reference", "description": "Agreed reference deployment"}],
        entry_criteria=["The scope under test has approved acceptance criteria",
                        "Test environment and synthetic data are available"],
        exit_criteria=["Every criterion has at least one reviewed test",
                       "No critical finding remains open or unwaived"],
        suites=list(suites.values()),
        coverage=matrix.model_dump(by_alias=True),
        gaps=[{"criterionId": r.criterion_id, "itemStableId": r.item_stable_id,
               "text": r.criterion_text, "reason": "No test covers this criterion"}
              for r in matrix.rows if not r.covered],
        assembled_by=actor_id, assembled_at=utcnow(),
    )
    await testbooks.insert(book)
    await audit.record("testbook.assembled", project_id=project_id, actor_id=actor_id,
                       object_type="testbook", object_id=book.id, object_version=version,
                       detail={"cases": len(cases), "gaps": len(book.gaps)})
    return book


def export_feature_files(cases: list[TestCase], dialect: str = "en") -> dict[str, str]:
    """Gherkin .feature files keyed by filename."""
    files: dict[str, str] = {}
    for case in cases:
        if not case.gherkin:
            continue
        name = f"{case.stable_id}.feature"
        files[name] = gherkin_service.render_feature(case.gherkin, dialect)
    return files
