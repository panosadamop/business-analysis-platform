"""Test, Gherkin and testbook endpoints (section 13)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Response

from app.api.deps import ProjectContext, ProjectCtx, requires
from app.core.errors import NotFound
from app.core.policy import Permission
from app.models.testing import (CoverageMatrix, GherkinValidation, Testbook,
                                TestCase, TestCaseCreate, TestCaseUpdate)
from app.repositories import test_cases, testbooks
from app.services import gherkin as gherkin_service
from app.services import testing as testing_service

router = APIRouter(tags=["tests"], prefix="/projects/{project_id}")


@router.get("/tests", response_model=list[TestCase])
async def list_tests(project_id: str, ctx: ProjectCtx,
                     story_id: str | None = Query(None),
                     test_type: str | None = Query(None)) -> list[TestCase]:
    ctx.require(Permission.TEST_READ)
    query: dict[str, Any] = {"projectId": project_id}
    if story_id:
        query["storyId"] = story_id
    if test_type:
        query["testType"] = test_type
    return await test_cases.list(query, sort=[("stableId", 1)], limit=5000)


@router.post("/tests", response_model=TestCase, status_code=201)
async def create_test(project_id: str, payload: TestCaseCreate,
                      ctx: ProjectContext = requires(Permission.TEST_EDIT)) -> TestCase:
    return await testing_service.create_test(project_id, payload, actor_id=ctx.user.id)


@router.patch("/tests/{test_id}", response_model=TestCase)
async def update_test(project_id: str, test_id: str, payload: TestCaseUpdate,
                      ctx: ProjectContext = requires(Permission.TEST_EDIT)) -> TestCase:
    return await testing_service.update_test(project_id, test_id, payload,
                                             actor_id=ctx.user.id)


@router.get("/tests/{test_id}/gherkin")
async def render_gherkin(project_id: str, test_id: str, ctx: ProjectCtx,
                         dialect: str = Query("en")) -> dict[str, Any]:
    """Display dialect rendering of the single stored canonical structure."""
    ctx.require(Permission.TEST_READ)
    case = await test_cases.get(test_id, projectId=project_id)
    if not case:
        raise NotFound("Test case not found")
    if not case.gherkin:
        return {"text": None, "dialect": dialect,
                "note": "This test has no Gherkin scenario yet."}
    text = gherkin_service.render_feature(case.gherkin, dialect)
    return {"text": text, "dialect": dialect,
            "validation": gherkin_service.validate(text, dialect).model_dump(by_alias=True)}


@router.post("/tests/validate-gherkin", response_model=GherkinValidation)
async def validate_gherkin(project_id: str, body: dict[str, str],
                           ctx: ProjectCtx) -> GherkinValidation:
    ctx.require(Permission.TEST_READ)
    return gherkin_service.validate(body.get("text", ""), body.get("dialect"))


@router.get("/tests/coverage", response_model=CoverageMatrix)
async def coverage(project_id: str, ctx: ProjectCtx,
                   root_id: str | None = Query(None)) -> CoverageMatrix:
    ctx.require(Permission.TEST_READ)
    return await testing_service.coverage(project_id, root_id=root_id)


@router.get("/testbooks", response_model=list[Testbook])
async def list_testbooks(project_id: str, ctx: ProjectCtx) -> list[Testbook]:
    ctx.require(Permission.TEST_READ)
    return await testbooks.list({"projectId": project_id}, sort=[("version", -1)])


@router.post("/testbooks", response_model=Testbook, status_code=201)
async def assemble(project_id: str, body: dict[str, Any],
                   ctx: ProjectContext = requires(Permission.TEST_EDIT)) -> Testbook:
    return await testing_service.assemble_testbook(
        project_id, name=body.get("name", "Project testbook"),
        release_scope=body.get("releaseScope"), actor_id=ctx.user.id)


@router.get("/testbooks/{testbook_id}/features")
async def download_features(project_id: str, testbook_id: str, ctx: ProjectCtx,
                            dialect: str = Query("en")) -> Response:
    """Gherkin .feature files for the assembled testbook."""
    ctx.require(Permission.TEST_READ)
    book = await testbooks.get(testbook_id, projectId=project_id)
    if not book:
        raise NotFound("Testbook not found")
    cases = await test_cases.list({"projectId": project_id})
    files = testing_service.export_feature_files(cases, dialect)
    body = "\n\n".join(f"# ==== {name} ====\n{content}"
                       for name, content in sorted(files.items()))
    return Response(content=body, media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition":
                             f'attachment; filename="{project_id}-features.txt"'})
