"""Backlog, estimates and specification endpoints (sections 9 and 11)."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import ProjectContext, ProjectCtx, requires
from app.core.errors import NotFound
from app.core.policy import Permission
from app.models.analysis import Specification, SpecificationCreate
from app.models.backlog import (ArtifactVersion, BacklogItem, BacklogItemCreate,
                                BacklogItemUpdate, BacklogNode, Estimate,
                                EstimateCreate, EstimateRollup, RateCard)
from app.models.common import ItemType
from app.repositories import (artifact_versions, backlog_items, dependency_links,
                              estimates, rate_cards, specifications, test_cases)
from app.services import audit, backlog as backlog_service
from app.services.estimation import (effective_rate_card, inconsistency_warnings,
                                     rollup, save_estimate)

router = APIRouter(tags=["backlog"], prefix="/projects/{project_id}")


@router.get("/backlog/tree", response_model=list[BacklogNode])
async def backlog_tree(project_id: str, ctx: ProjectCtx,
                       root_id: str | None = Query(None)) -> list[BacklogNode]:
    ctx.require(Permission.BACKLOG_READ)
    return await backlog_service.tree(project_id, root_id=root_id)


@router.get("/backlog/items", response_model=list[BacklogItem])
async def list_items(project_id: str, ctx: ProjectCtx,
                     type: str | None = Query(None),
                     iteration_id: str | None = Query(None),
                     state: str | None = Query(None)) -> list[BacklogItem]:
    ctx.require(Permission.BACKLOG_READ)
    query: dict[str, Any] = {"projectId": project_id}
    if type:
        query["type"] = type
    if iteration_id:
        query["iterationId"] = iteration_id
    if state:
        query["state"] = state
    return await backlog_items.list(query, sort=[("order", 1)], limit=5000)


@router.post("/backlog/items", response_model=dict, status_code=201)
async def create_item(project_id: str, payload: BacklogItemCreate,
                      ctx: ProjectContext = requires(Permission.BACKLOG_EDIT)
                      ) -> dict[str, Any]:
    item, version = await backlog_service.create_item(project_id, payload,
                                                      actor_id=ctx.user.id)
    return {"item": item.model_dump(by_alias=True),
            "version": version.model_dump(by_alias=True)}


@router.get("/backlog/items/{item_id}")
async def get_item(project_id: str, item_id: str, ctx: ProjectCtx) -> dict[str, Any]:
    ctx.require(Permission.BACKLOG_READ)
    item = await backlog_items.get(item_id, projectId=project_id)
    if not item:
        raise NotFound("Backlog item not found")
    version = await backlog_service.current_version(item)
    history = await artifact_versions.list({"itemId": item_id}, sort=[("version", -1)])
    estimate = await estimates.find_one({"projectId": project_id, "itemId": item_id,
                                         "superseded": False, "isRoughParent": False})
    rough = await estimates.find_one({"projectId": project_id, "itemId": item_id,
                                      "superseded": False, "isRoughParent": True})
    tests = await test_cases.list({"projectId": project_id, "storyId": item_id})
    dependencies = await dependency_links.list({"projectId": project_id,
                                                "fromId": item_id})
    card = await effective_rate_card(project_id) if ctx.has(Permission.COST_READ) else None
    rollup_result = await rollup(project_id, item_id,
                                 hours_per_person_day=ctx.project.calendar.hours_per_person_day,
                                 rate_card=card)
    return {
        "item": item.model_dump(by_alias=True),
        "version": version.model_dump(by_alias=True),
        "history": [{"id": v.id, "version": v.version, "state": str(v.state),
                     "authorId": v.author_id, "createdAt": v.created_at,
                     "changeNote": v.change_note,
                     "generatedByRole": v.generated_by_role, "modelId": v.model_id,
                     "approvalEventId": v.approval_event_id,
                     "inheritedFromEventId": v.inherited_from_event_id}
                    for v in history],
        "estimate": estimate.model_dump(by_alias=True) if estimate else None,
        "roughParentEstimate": rough.model_dump(by_alias=True) if rough else None,
        "estimateWarnings": inconsistency_warnings(estimate) if estimate else [],
        "rollup": rollup_result.model_dump(by_alias=True),
        "tests": [{"id": t.id, "stableId": t.stable_id, "title": t.title,
                   "testType": str(t.test_type), "state": str(t.state),
                   "reviewState": t.review_state} for t in tests],
        "dependencies": [d.model_dump(by_alias=True) for d in dependencies],
    }


@router.patch("/backlog/items/{item_id}")
async def update_item(project_id: str, item_id: str, payload: BacklogItemUpdate,
                      ctx: ProjectContext = requires(Permission.BACKLOG_EDIT)
                      ) -> dict[str, Any]:
    item, version = await backlog_service.update_item(project_id, item_id, payload,
                                                      actor_id=ctx.user.id)
    return {"item": item.model_dump(by_alias=True),
            "version": version.model_dump(by_alias=True)}


@router.post("/backlog/items/{item_id}/move", response_model=BacklogItem)
async def move_item(project_id: str, item_id: str, body: dict[str, Any],
                    ctx: ProjectContext = requires(Permission.BACKLOG_EDIT)
                    ) -> BacklogItem:
    return await backlog_service.move_item(project_id, item_id,
                                           parent_id=body.get("parentId"),
                                           order=float(body.get("order", 0)),
                                           actor_id=ctx.user.id)


@router.delete("/backlog/items/{item_id}")
async def archive_item(project_id: str, item_id: str,
                       ctx: ProjectContext = requires(Permission.BACKLOG_EDIT)
                       ) -> dict[str, int]:
    count = await backlog_service.delete_item(project_id, item_id, actor_id=ctx.user.id)
    return {"archived": count}


@router.get("/backlog/items/{item_id}/versions/{version}", response_model=ArtifactVersion)
async def get_version(project_id: str, item_id: str, version: int,
                      ctx: ProjectCtx) -> ArtifactVersion:
    ctx.require(Permission.BACKLOG_READ)
    found = await artifact_versions.find_one({"itemId": item_id, "version": version})
    if not found:
        raise NotFound("Version not found")
    return found


@router.get("/backlog/items/{item_id}/diff")
async def version_diff(project_id: str, item_id: str, ctx: ProjectCtx,
                       base: int = Query(...), compare: int = Query(...)
                       ) -> dict[str, Any]:
    ctx.require(Permission.BACKLOG_READ)
    first = await artifact_versions.find_one({"itemId": item_id, "version": base})
    second = await artifact_versions.find_one({"itemId": item_id, "version": compare})
    if not first or not second:
        raise NotFound("One of the versions does not exist")
    fields = ["title", "description", "actor", "need", "benefit", "functionalNotes",
              "technicalNotes", "nfrNotes"]
    a = first.model_dump(by_alias=True)
    b = second.model_dump(by_alias=True)
    changes = {f: {"from": a.get(f), "to": b.get(f)} for f in fields
               if a.get(f) != b.get(f)}
    criteria_a = {c["id"]: c["text"] for c in a.get("acceptanceCriteria", [])}
    criteria_b = {c["id"]: c["text"] for c in b.get("acceptanceCriteria", [])}
    return {
        "base": base, "compare": compare, "fields": changes,
        "criteria": {
            "added": [{"id": k, "text": v} for k, v in criteria_b.items()
                      if k not in criteria_a],
            "removed": [{"id": k, "text": v} for k, v in criteria_a.items()
                        if k not in criteria_b],
            "changed": [{"id": k, "from": criteria_a[k], "to": v}
                        for k, v in criteria_b.items()
                        if k in criteria_a and criteria_a[k] != v],
        },
    }


@router.post("/backlog/items/{item_id}/estimate", response_model=Estimate)
async def set_estimate(project_id: str, item_id: str, payload: EstimateCreate,
                       ctx: ProjectContext = requires(Permission.ESTIMATE_EDIT)
                       ) -> Estimate:
    return await save_estimate(project_id, item_id, payload, actor_id=ctx.user.id)


@router.get("/backlog/items/{item_id}/rollup", response_model=EstimateRollup)
async def item_rollup(project_id: str, item_id: str, ctx: ProjectCtx) -> EstimateRollup:
    ctx.require(Permission.BACKLOG_READ)
    card = await effective_rate_card(project_id) if ctx.has(Permission.COST_READ) else None
    return await rollup(project_id, item_id,
                        hours_per_person_day=ctx.project.calendar.hours_per_person_day,
                        rate_card=card)


@router.get("/backlog/dependencies")
async def dependencies(project_id: str, ctx: ProjectCtx) -> dict[str, Any]:
    ctx.require(Permission.BACKLOG_READ)
    links = await dependency_links.list({"projectId": project_id})
    cycles = await backlog_service.detect_dependency_cycles(project_id)
    unowned = [d.model_dump(by_alias=True) for d in links if not d.owner_id and d.external]
    return {"links": [d.model_dump(by_alias=True) for d in links],
            "cycles": cycles, "unowned": unowned}


@router.post("/backlog/dependencies", status_code=201)
async def add_dependency(project_id: str, body: dict[str, Any],
                         ctx: ProjectContext = requires(Permission.BACKLOG_EDIT)
                         ) -> dict[str, Any]:
    from app.models.knowledge import DependencyLink

    link = DependencyLink(project_id=project_id, from_id=body["fromId"],
                          to_id=body["toId"], kind=body.get("kind", "blocks"),
                          owner_id=body.get("ownerId"), note=body.get("note"))
    await dependency_links.insert(link)
    cycles = await backlog_service.detect_dependency_cycles(project_id)
    return {"link": link.model_dump(by_alias=True), "cycles": cycles}


@router.get("/rate-cards", response_model=list[RateCard])
async def list_rate_cards(project_id: str,
                          ctx: ProjectContext = requires(Permission.RATE_READ)
                          ) -> list[RateCard]:
    return await rate_cards.list({"projectId": project_id},
                                 sort=[("effectiveFrom", -1)])


@router.post("/rate-cards", response_model=RateCard, status_code=201)
async def create_rate_card(project_id: str, body: dict[str, Any],
                           ctx: ProjectContext = requires(Permission.RATE_MANAGE)
                           ) -> RateCard:
    card = RateCard(project_id=project_id, name=body["name"],
                    currency=body.get("currency", ctx.project.currency),
                    effective_from=date.fromisoformat(body["effectiveFrom"]),
                    effective_to=date.fromisoformat(body["effectiveTo"])
                    if body.get("effectiveTo") else None,
                    rates={k: str(v) for k, v in body.get("rates", {}).items()},
                    non_labor_lines=body.get("nonLaborLines", []),
                    contingency_percent=float(body.get("contingencyPercent", 0)),
                    created_by=ctx.user.id)
    await rate_cards.insert(card)
    await audit.record("rate_card.created", project_id=project_id, actor_id=ctx.user.id,
                       object_type="rateCard", object_id=card.id)
    return card


@router.get("/specifications", response_model=list[Specification])
async def list_specifications(project_id: str, ctx: ProjectCtx,
                              kind: str | None = Query(None)) -> list[Specification]:
    ctx.require(Permission.SPEC_READ)
    query: dict[str, Any] = {"projectId": project_id}
    if kind:
        query["kind"] = kind
    return await specifications.list(query, sort=[("createdAt", -1)])


@router.post("/specifications", response_model=Specification, status_code=201)
async def create_specification(project_id: str, payload: SpecificationCreate,
                               ctx: ProjectContext = requires(Permission.SPEC_EDIT)
                               ) -> Specification:
    """Write a specification by hand instead of generating one."""
    spec = Specification(project_id=project_id, author_id=ctx.user.id,
                         **payload.model_dump(by_alias=False))
    await specifications.insert(spec)
    await audit.record("specification.created", project_id=project_id,
                       actor_id=ctx.user.id, object_type="specification",
                       object_id=spec.id, detail={"kind": str(payload.kind),
                                                  "authored": "manual"})
    return spec


@router.patch("/specifications/{specification_id}", response_model=Specification)
async def update_specification(project_id: str, specification_id: str,
                               body: dict[str, Any],
                               ctx: ProjectContext = requires(Permission.SPEC_EDIT)
                               ) -> Specification:
    spec = await specifications.get(specification_id, projectId=project_id)
    if not spec:
        raise NotFound("Specification not found")
    changes = {k: v for k, v in body.items()
               if k in {"title", "body", "diagramSource", "structured", "changeNote"}}
    if spec.state == "approved":
        changes["version"] = spec.version + 1
        changes["state"] = "draft"
    changes["authorId"] = ctx.user.id
    return await specifications.update(specification_id, changes, projectId=project_id)
