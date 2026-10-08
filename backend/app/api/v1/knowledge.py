"""Knowledge, questions and traceability endpoints (section 7)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import ProjectContext, ProjectCtx, requires
from app.core.errors import ConflictState, NotFound
from app.core.policy import Permission
from app.core.utils import utcnow
from app.models.common import Classification
from app.models.common import EvidenceLocator
from app.models.knowledge import (EvidenceLink, EvidenceLinkCreate, GlossaryTerm,
                                  GlossaryTermCreate, Question, QuestionCreate,
                                  QuestionResolve, Requirement,
                                  RequirementCreate, RequirementUpdate,
                                  RequirementVersion, SearchHit)
from app.repositories import (artifact_versions, backlog_items, evidence_links,
                              glossary, questions, requirements,
                              requirement_versions, source_documents,
                              source_versions, test_cases)
from app.services import audit, search

router = APIRouter(tags=["knowledge"], prefix="/projects/{project_id}")


def _allowed_classifications(ctx: ProjectContext) -> set[str]:
    if ctx.has(Permission.SOURCE_RAW_READ):
        return {str(c) for c in Classification}
    return {str(Classification.SHAREABLE), str(Classification.CONFIDENTIAL)}


@router.get("/requirements", response_model=list[Requirement])
async def list_requirements(project_id: str, ctx: ProjectCtx,
                            type: str | None = Query(None),
                            state: str | None = Query(None)) -> list[Requirement]:
    ctx.require(Permission.BACKLOG_READ)
    query: dict[str, Any] = {"projectId": project_id}
    if type:
        query["type"] = type
    if state:
        query["state"] = state
    return await requirements.list(query, sort=[("stableId", 1)], limit=2000)


@router.post("/requirements", response_model=Requirement, status_code=201)
async def create_requirement(project_id: str, payload: RequirementCreate,
                             ctx: ProjectContext = requires(Permission.BACKLOG_EDIT)
                             ) -> Requirement:
    index = await requirements.count({"projectId": project_id}) + 1
    requirement = Requirement(project_id=project_id, stable_id=f"REQ-{index:03d}",
                              **payload.model_dump(by_alias=False))
    await requirements.insert(requirement)
    await audit.record("requirement.created", project_id=project_id, actor_id=ctx.user.id,
                       object_type="requirement", object_id=requirement.id)
    return requirement


@router.patch("/requirements/{requirement_id}", response_model=Requirement)
async def update_requirement(project_id: str, requirement_id: str,
                             payload: RequirementUpdate,
                             ctx: ProjectContext = requires(Permission.BACKLOG_EDIT)
                             ) -> Requirement:
    current = await requirements.get(requirement_id, projectId=project_id)
    if not current:
        raise NotFound("Requirement not found")
    await requirement_versions.insert(RequirementVersion(
        project_id=project_id, requirement_id=requirement_id, version=current.version,
        snapshot=current.model_dump(by_alias=True), state=current.state,
        author_id=ctx.user.id))
    changes = payload.model_dump(exclude_unset=True, by_alias=True, exclude_none=True)
    expected = changes.pop("rev", None)
    changes["version"] = current.version + 1
    return await requirements.update(requirement_id, changes, expected_rev=expected,
                                     projectId=project_id)


@router.get("/questions", response_model=list[Question])
async def list_questions(project_id: str, ctx: ProjectCtx,
                         status: str | None = Query(None),
                         severity: str | None = Query(None)) -> list[Question]:
    ctx.require(Permission.BACKLOG_READ)
    query: dict[str, Any] = {"projectId": project_id}
    if status:
        query["status"] = status
    if severity:
        query["severity"] = severity
    return await questions.list(query, sort=[("createdAt", -1)], limit=1000)


@router.post("/questions", response_model=Question, status_code=201)
async def create_question(project_id: str, payload: QuestionCreate,
                          ctx: ProjectContext = requires(Permission.BACKLOG_EDIT)
                          ) -> Question:
    index = await questions.count({"projectId": project_id}) + 1
    question = Question(project_id=project_id, stable_id=f"Q-{index:03d}",
                        **payload.model_dump(by_alias=False))
    await questions.insert(question)
    return question


@router.post("/questions/{question_id}/resolve", response_model=Question)
async def resolve_question(project_id: str, question_id: str, payload: QuestionResolve,
                           ctx: ProjectContext = requires(Permission.BACKLOG_EDIT)
                           ) -> Question:
    question = await questions.get(question_id, projectId=project_id)
    if not question:
        raise NotFound("Question not found")
    history = question.history + [{
        "at": utcnow(), "by": ctx.user.id, "from": str(question.status),
        "to": str(payload.status), "answer": payload.answer}]
    updated = await questions.update(question_id, {
        "status": str(payload.status), "answer": payload.answer,
        "answeredBy": ctx.user.id, "answeredAt": utcnow(), "history": history},
        projectId=project_id)
    await audit.record("question.resolved", project_id=project_id, actor_id=ctx.user.id,
                       object_type="question", object_id=question_id,
                       detail={"status": str(payload.status)})
    return updated


@router.get("/glossary", response_model=list[GlossaryTerm])
async def list_glossary(project_id: str, ctx: ProjectCtx) -> list[GlossaryTerm]:
    ctx.require(Permission.BACKLOG_READ)
    return await glossary.list({"projectId": project_id}, sort=[("term", 1)], limit=1000)


@router.post("/glossary", response_model=GlossaryTerm, status_code=201)
async def create_term(project_id: str, payload: GlossaryTermCreate,
                      ctx: ProjectContext = requires(Permission.BACKLOG_EDIT)
                      ) -> GlossaryTerm:
    if await glossary.exists({"projectId": project_id, "term": payload.term}):
        raise ConflictState("That term is already in the project glossary")
    term = GlossaryTerm(project_id=project_id, **payload.model_dump(by_alias=False))
    await glossary.insert(term)
    await audit.record("glossary.created", project_id=project_id, actor_id=ctx.user.id,
                       object_type="glossaryTerm", object_id=term.id,
                       detail={"term": payload.term})
    return term


@router.delete("/glossary/{term_id}")
async def delete_term(project_id: str, term_id: str,
                      ctx: ProjectContext = requires(Permission.BACKLOG_EDIT)
                      ) -> dict[str, bool]:
    deleted = await glossary.delete(term_id, projectId=project_id)
    if not deleted:
        raise NotFound("Glossary term not found")
    return {"deleted": True}


@router.post("/evidence-links", response_model=EvidenceLink, status_code=201)
async def create_evidence_link(project_id: str, payload: EvidenceLinkCreate,
                               ctx: ProjectContext = requires(Permission.BACKLOG_EDIT)
                               ) -> EvidenceLink:
    """Record by hand that an artifact derives from a piece of evidence.

    Analysts need this when they recognise a link the analysis did not make, and
    it is what turns an unsupported statement into an evidence backed one.
    """
    version = await source_versions.get(payload.source_version_id, projectId=project_id)
    if not version:
        raise NotFound("Source version not found in this project")
    link = EvidenceLink(
        project_id=project_id,
        source_version_id=payload.source_version_id,
        source_chunk_id=payload.source_chunk_id,
        locator=EvidenceLocator(source_version_id=payload.source_version_id,
                                kind=payload.locator_kind,
                                value=payload.locator_value).model_dump(by_alias=True),
        target_type=payload.target_type, target_id=payload.target_id,
        target_version=payload.target_version, link_type=payload.link_type,
        rationale=payload.rationale, created_by=ctx.user.id)
    await evidence_links.insert(link)
    await audit.record("evidence_link.created", project_id=project_id,
                       actor_id=ctx.user.id, object_type="evidenceLink",
                       object_id=link.id,
                       detail={"targetType": payload.target_type,
                               "targetId": payload.target_id})
    return link


@router.delete("/evidence-links/{link_id}")
async def delete_evidence_link(project_id: str, link_id: str,
                               ctx: ProjectContext = requires(Permission.BACKLOG_EDIT)
                               ) -> dict[str, bool]:
    deleted = await evidence_links.delete(link_id, projectId=project_id)
    if not deleted:
        raise NotFound("Evidence link not found")
    await audit.record("evidence_link.deleted", project_id=project_id,
                       actor_id=ctx.user.id, object_type="evidenceLink",
                       object_id=link_id)
    return {"deleted": True}


@router.get("/search", response_model=list[SearchHit])
async def search_evidence(project_id: str, ctx: ProjectCtx, q: str = Query(..., min_length=2),
                          limit: int = Query(25, le=100)) -> list[SearchHit]:
    """Permission filtered bilingual search over current source versions."""
    ctx.require(Permission.SOURCE_READ)
    return await search.search(project_id, q,
                               allowed_classifications=_allowed_classifications(ctx),
                               limit=limit)


@router.get("/traceability")
async def traceability(project_id: str, ctx: ProjectCtx,
                       target_id: str | None = Query(None)) -> dict[str, Any]:
    """Evidence to requirement to backlog to test chain (REQ-KNOW-03)."""
    ctx.require(Permission.BACKLOG_READ)
    query: dict[str, Any] = {"projectId": project_id}
    if target_id:
        query["targetId"] = target_id
    links = await evidence_links.list(query, limit=5000)
    versions = {v.id: v for v in await source_versions.list({"projectId": project_id})}
    documents = {d.id: d for d in await source_documents.list({"projectId": project_id})}
    items = {i.id: i for i in await backlog_items.list({"projectId": project_id})}
    reqs = {r.id: r for r in await requirements.list({"projectId": project_id})}
    tests = await test_cases.list({"projectId": project_id})

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(node_id: str, kind: str, label: str, extra: dict[str, Any] | None = None) -> None:
        if node_id in seen:
            return
        seen.add(node_id)
        nodes.append({"id": node_id, "kind": kind, "label": label, **(extra or {})})

    for link in links:
        version = versions.get(link.source_version_id or "")
        document = documents.get(version.document_id) if version else None
        source_node = f"src:{link.source_version_id}"
        allowed = document and str(document.classification) in _allowed_classifications(ctx)
        add(source_node, "evidence",
            document.title if (document and allowed) else "Restricted source",
            {"restricted": not allowed,
             "locator": link.locator or {}})
        if link.target_type == "requirement":
            requirement = reqs.get(link.target_id)
            add(f"req:{link.target_id}", "requirement",
                requirement.title if requirement else link.target_id)
            edges.append({"from": source_node, "to": f"req:{link.target_id}",
                          "type": str(link.link_type)})
        elif link.target_type == "backlog_item":
            item = items.get(link.target_id)
            add(f"item:{link.target_id}", "backlog_item",
                f"{item.stable_id} {item.title}" if item else link.target_id)
            edges.append({"from": source_node, "to": f"item:{link.target_id}",
                          "type": str(link.link_type)})

    for test in tests:
        if not test.story_id:
            continue
        add(f"test:{test.id}", "test_case", f"{test.stable_id} {test.title}")
        item = items.get(test.story_id)
        if item:
            add(f"item:{item.id}", "backlog_item", f"{item.stable_id} {item.title}")
            edges.append({"from": f"item:{item.id}", "to": f"test:{test.id}",
                          "type": "verifies"})

    orphan_items = [
        {"id": i.id, "stableId": i.stable_id, "title": i.title}
        for i in items.values()
        if i.type == "story" and f"item:{i.id}" not in seen
    ]
    return {"nodes": nodes, "edges": edges, "orphanStories": orphan_items,
            "note": ("Items without an evidence link are either analyst assumptions or "
                     "need a citation before approval.")}
