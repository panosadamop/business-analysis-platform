"""Sequential analyst orchestration: BA -> Technical Analyst -> QA (section 8).

The orchestrator runs roles in order on explicit artifact versions, validates
every output against the versioned schema before persisting, records the full
provenance of each artifact, stores a checkpoint per stage so a failed job can
resume, and keeps the correction loop bounded. A specialist review never counts
as human approval.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.ai import gateway, prompts, schemas
from app.ai.adapters.base import AdapterUnavailable
from app.core.errors import PolicyBlocked, ValidationFailed
from app.core.utils import new_id, utcnow
from app.models.analysis import (AnalysisJob, AnalysisStage, AnalysisRunRequest,
                                 FindingStatus, ReviewFinding, Specification,
                                 SpecificationKind, StageStatus)
from app.models.backlog import (AcceptanceCriterion, ArtifactVersion,
                                BacklogItem, EstimateCreate, RoleEffort)
from app.models.common import (AnalystRole, ArtifactState, Citation,
                               EvidenceLocator, ItemType, JobStatus, Money,
                               Priority, Provenance, Severity)
from app.models.knowledge import (DependencyLink, EvidenceLink, GlossaryTerm,
                                  Question, Requirement, RequirementType)
from app.models.project import ANALYST_ORDER, DEFAULT_ANALYSTS, Project
from app.models.testing import (GherkinFeature, GherkinScenario, GherkinStep,
                                TestCase, TestStep, TestType)
from app.repositories import (analysis_jobs, artifact_versions, backlog_items,
                              dependency_links, evidence_links, findings,
                              glossary, projects, questions, requirements,
                              specifications, test_cases)
from app.services import audit, backlog as backlog_service, sources
from app.services.estimation import save_estimate

log = logging.getLogger(__name__)

ROLE_ORDER = ANALYST_ORDER


class JobCancelled(RuntimeError):
    pass


async def start_job(project_id: str, request: AnalysisRunRequest, *,
                    actor_id: str) -> AnalysisJob:
    project = await projects.require(project_id)
    if request.idempotency_key:
        existing = await analysis_jobs.find_one({"projectId": project_id,
                                                 "idempotencyKey": request.idempotency_key})
        if existing:
            return existing
    roles = _roles_for(project, request)
    scope = request.model_dump(by_alias=True)
    scope["roles"] = [str(role) for role in roles]
    job = AnalysisJob(
        project_id=project_id,
        scope=scope,
        status=JobStatus.QUEUED,
        stages=[AnalysisStage(role=role) for role in roles],
        requested_by=actor_id,
        max_cycles=request.max_cycles or project.quality_gates.max_correction_cycles,
        idempotency_key=request.idempotency_key,
    )
    await analysis_jobs.insert(job)
    await audit.record("analysis.queued", project_id=project_id, actor_id=actor_id,
                       object_type="analysisJob", object_id=job.id,
                       detail={"roles": [str(r) for r in roles]})
    return job


def _roles_for(project: Project, request: AnalysisRunRequest) -> list[AnalystRole]:
    """The stages of a run: the project's analysts unless the request names some.

    A request may narrow a run to some of the project's analysts, never add one
    the project has switched off.
    """
    enabled = project.enabled_analysts or DEFAULT_ANALYSTS
    if "roles" in request.model_fields_set and request.roles:
        requested = {AnalystRole(role) for role in request.roles}
        disabled = [role for role in ROLE_ORDER if role in requested and role not in enabled]
        if disabled:
            raise ValidationFailed(
                "This project does not use the "
                + ", ".join(str(role).replace("_", " ") for role in disabled)
                + ". Enable it in the project setup or leave it out of the run.",
                code="analyst_not_enabled",
                details={"disabled": [str(r) for r in disabled],
                         "enabled": [str(r) for r in enabled]})
    else:
        requested = set(enabled)
    return [role for role in ROLE_ORDER if role in requested]


async def run_job(job_id: str) -> AnalysisJob:
    """Execute the stages of a job, resuming from the last validated stage."""
    job = await analysis_jobs.require(job_id)
    project = await projects.require(job.project_id)
    request = AnalysisRunRequest(**{k: v for k, v in job.scope.items()
                                    if k in AnalysisRunRequest.model_fields
                                    or k in {"itemIds", "sourceVersionIds", "roles",
                                             "regenerate", "mergePreview",
                                             "generateSpecifications", "generateTests",
                                             "maxCycles", "idempotencyKey"}})

    job.status = JobStatus.RUNNING
    job.started_at = job.started_at or utcnow()
    await analysis_jobs.replace(job)

    chunks = await sources.chunk_ids_for_context(project.id)
    if not chunks:
        job.status = JobStatus.FAILED
        job.message = ("No readable evidence is available. Upload sources or fix failed "
                       "extractions before running the analysis.")
        job.finished_at = utcnow()
        await analysis_jobs.replace(job)
        return job

    total_stages = len(job.stages)
    try:
        for index, stage in enumerate(job.stages):
            fresh = await analysis_jobs.require(job_id)
            if fresh.cancel_requested:
                raise JobCancelled()
            if stage.status == StageStatus.SUCCEEDED:
                continue

            stage.status = StageStatus.RUNNING
            stage.started_at = utcnow()
            job.message = f"Running {stage.role}"
            await analysis_jobs.replace(job)

            backlog_json = await _backlog_snapshot(project.id)
            try:
                result = await gateway.run_role(
                    project, str(stage.role), chunks=chunks,
                    backlog_json=backlog_json, actor_id=job.requested_by)
            except PolicyBlocked as blocked:
                stage.status = StageStatus.BLOCKED
                stage.error = blocked.message
                job.status = JobStatus.PAUSED
                job.message = (f"{stage.role} was blocked by the data policy gate. "
                               "No project content left company infrastructure.")
                job.finished_at = utcnow()
                await analysis_jobs.replace(job)
                return job
            except AdapterUnavailable as unavailable:
                stage.status = StageStatus.FAILED
                stage.error = str(unavailable)
                job.status = JobStatus.PAUSED
                job.message = (f"{stage.role} could not run: {unavailable}. "
                               "The job is paused and can be resumed.")
                job.finished_at = utcnow()
                await analysis_jobs.replace(job)
                return job

            counts = await _persist(project, stage.role, result, request,
                                    actor_id=job.requested_by or "system",
                                    job_id=job.id)

            stage.status = StageStatus.SUCCEEDED
            stage.finished_at = utcnow()
            stage.usage = result.usage
            stage.output_summary = counts
            stage.checkpoint = {"persisted": counts, "at": utcnow().isoformat()}
            stage.input_manifest = {
                "sourceVersionIds": sorted({c.source_version_id for c in chunks}),
                "chunkCount": len(chunks),
                "promptTemplateVersion": prompts.PROMPT_TEMPLATE_VERSION,
                "schemaVersion": schemas.SCHEMA_VERSION,
            }
            for key, value in counts.items():
                job.created_counts[key] = job.created_counts.get(key, 0) + value
            for warning in result.warnings:
                job.warnings.append({"stage": str(stage.role), "message": warning})
            job.progress = round((index + 1) / total_stages, 2)
            await analysis_jobs.replace(job)

        await _bound_correction_loop(project, job)

        job.status = JobStatus.SUCCEEDED
        job.message = "Analysis complete. Every artifact is a draft awaiting human approval."
        job.finished_at = utcnow()
        job.total_cost = _sum_cost(job)
        await analysis_jobs.replace(job)
    except JobCancelled:
        job.status = JobStatus.CANCELLED
        job.message = "Cancelled by request. Completed stages are preserved."
        job.finished_at = utcnow()
        await analysis_jobs.replace(job)
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("analysis job %s failed", job_id)
        job.status = JobStatus.FAILED
        job.message = f"Unexpected failure: {exc}"
        job.finished_at = utcnow()
        await analysis_jobs.replace(job)
    return job


def _sum_cost(job: AnalysisJob) -> Money:
    total = Money.of(0, "EUR")
    for stage in job.stages:
        if stage.usage and stage.usage.cost:
            total = total.plus(stage.usage.cost)
    return total


async def _backlog_snapshot(project_id: str) -> str:
    items = await backlog_items.list({"projectId": project_id,
                                      "type": {"$in": ["story", "feature", "epic"]}},
                                     sort=[("order", 1)], limit=400)
    versions = await artifact_versions.list(
        {"_id": {"$in": [i.current_version_id for i in items if i.current_version_id]}})
    by_item = {v.item_id: v for v in versions}
    snapshot = []
    for item in items:
        version = by_item.get(item.id)
        if not version:
            continue
        snapshot.append({
            "id": item.id,
            "stableId": item.stable_id,
            "type": str(item.type),
            "title": version.title,
            "description": version.description,
            "priority": str(item.priority),
            "acceptanceCriteria": [
                {"id": c.id, "text": c.text, "outcomeLevel": c.outcome_level}
                for c in version.acceptance_criteria
            ],
        })
    return json.dumps(snapshot, ensure_ascii=False)


# --- persistence ------------------------------------------------------------

async def _persist(project: Project, role: AnalystRole, result: gateway.GatewayResult,
                   request: AnalysisRunRequest, *, actor_id: str,
                   job_id: str) -> dict[str, int]:
    if role == AnalystRole.BA:
        return await _persist_ba(project, result, request, actor_id=actor_id, job_id=job_id)
    if role == AnalystRole.UX:
        return await _persist_ux(project, result, request, actor_id=actor_id, job_id=job_id)
    if role == AnalystRole.DATA:
        return await _persist_data(project, result, request, actor_id=actor_id, job_id=job_id)
    if role == AnalystRole.TA:
        return await _persist_ta(project, result, request, actor_id=actor_id, job_id=job_id)
    return await _persist_qa(project, result, request, actor_id=actor_id, job_id=job_id)


def _citations(raw: list[Any]) -> list[Citation]:
    out: list[Citation] = []
    for item in raw or []:
        data = item if isinstance(item, dict) else item.model_dump(by_alias=True)
        source_version_id = data.get("sourceVersionId") or data.get("source_version_id")
        if not source_version_id:
            continue
        out.append(Citation(
            locator=EvidenceLocator(
                source_version_id=source_version_id,
                kind=data.get("locatorKind") or data.get("locator_kind") or "paragraph",
                value=data.get("locatorValue") or data.get("locator_value") or "",
            ),
            quote=data.get("quote"),
        ))
    return out


async def _persist_ba(project: Project, result: gateway.GatewayResult,
                      request: AnalysisRunRequest, *, actor_id: str,
                      job_id: str) -> dict[str, int]:
    payload: schemas.BAOutput = result.validated
    counts = {"requirements": 0, "questions": 0, "glossary": 0,
              "epics": 0, "features": 0, "stories": 0, "specifications": 0}

    existing_requirements = {
        r.title.strip().lower()
        for r in await requirements.list({"projectId": project.id})
    }
    index = _next_number((r.stable_id for r in await requirements.list(
        {"projectId": project.id})), "REQ") - 1

    for entry in list(payload.requirements) + list(payload.business_rules):
        if entry.title.strip().lower() in existing_requirements and not request.regenerate:
            continue
        index += 1
        requirement = Requirement(
            project_id=project.id, stable_id=f"REQ-{index:03d}",
            type=RequirementType(entry.type) if entry.type in set(RequirementType)
            else RequirementType.BUSINESS,
            title=entry.title, statement=entry.statement, rationale=entry.rationale,
            provenance=Provenance(entry.provenance),
            priority=Priority(entry.priority) if entry.priority in set(Priority)
            else Priority.MEDIUM,
            confidence=entry.confidence, citations=_citations(entry.citations),
            created_by_role=str(AnalystRole.BA),
        )
        await requirements.insert(requirement)
        existing_requirements.add(entry.title.strip().lower())
        counts["requirements"] += 1
        await _link_evidence(project.id, requirement.citations, "requirement", requirement.id)

    existing_questions = await questions.list({"projectId": project.id})
    asked = {q.title.strip().lower() for q in existing_questions}
    q_index = _next_number((q.stable_id for q in existing_questions), "Q") - 1
    for entry in payload.questions:
        if entry.title.strip().lower() in asked and not request.regenerate:
            continue
        asked.add(entry.title.strip().lower())
        q_index += 1
        question = Question(
            project_id=project.id, stable_id=f"Q-{q_index:03d}", kind=entry.kind,
            severity=Severity(entry.severity), title=entry.title, detail=entry.detail,
            proposed_clarification=entry.proposed_clarification,
            citations=_citations(entry.citations),
        )
        await questions.insert(question)
        counts["questions"] += 1

    for term in payload.glossary:
        name = (term.get("term") or "").strip()
        if not name:
            continue
        if await glossary.exists({"projectId": project.id, "term": name}):
            continue
        await glossary.insert(GlossaryTerm(
            project_id=project.id, term=name,
            definition=term.get("definition", ""),
            language=term.get("language", str(project.output_language)),
            citations=_citations(term.get("citations", [])),
        ))
        counts["glossary"] += 1

    # Backlog hierarchy. Existing titles are not duplicated unless regenerating.
    existing_titles = {
        (str(i.type), i.title.strip().lower())
        for i in await backlog_items.list({"projectId": project.id})
    }
    for epic_out in payload.epics:
        if ("epic", epic_out.title.strip().lower()) in existing_titles and not request.regenerate:
            epic = await backlog_items.find_one({"projectId": project.id, "type": "epic",
                                                 "title": epic_out.title})
        else:
            epic, _ = await _create_item(project, ItemType.EPIC, None, epic_out.title,
                                         epic_out.description, epic_out.acceptance_criteria,
                                         actor_id=actor_id)
            counts["epics"] += 1
        if not epic:
            continue
        for feature_out in epic_out.features:
            key = ("feature", feature_out.title.strip().lower())
            if key in existing_titles and not request.regenerate:
                feature = await backlog_items.find_one({"projectId": project.id,
                                                        "type": "feature",
                                                        "title": feature_out.title})
            else:
                feature, _ = await _create_item(project, ItemType.FEATURE, epic.id,
                                                feature_out.title, feature_out.description,
                                                feature_out.acceptance_criteria,
                                                actor_id=actor_id)
                counts["features"] += 1
            if not feature:
                continue
            for story_out in feature_out.stories:
                skey = ("story", story_out.title.strip().lower())
                if skey in existing_titles and not request.regenerate:
                    continue
                story, version = await _create_item(
                    project, ItemType.STORY, feature.id, story_out.title,
                    story_out.description, story_out.acceptance_criteria,
                    actor_id=actor_id, story=story_out)
                counts["stories"] += 1
                existing_titles.add(skey)
                if story_out.estimate_hint_hours:
                    await save_estimate(project.id, story.id, EstimateCreate(
                        method="ai_proposed",
                        story_points=story_out.story_points_hint,
                        role_efforts=[RoleEffort(role="analysis",
                                                 hours=story_out.estimate_hint_hours * 0.3),
                                      RoleEffort(role="engineering",
                                                 hours=story_out.estimate_hint_hours * 0.5),
                                      RoleEffort(role="qa",
                                                 hours=story_out.estimate_hint_hours * 0.2)],
                        confidence_label="indicative",
                        assumptions=["Proposed from scope and complexity templates. "
                                     "Not a commitment until reviewed."],
                    ), actor_id=actor_id)
                await _link_evidence(project.id, version.citations, "backlog_item", story.id,
                                     version.version)

    if payload.functional_specification and request.generate_specifications:
        counts["specifications"] += await _add_specification(request, Specification(
            project_id=project.id, kind=SpecificationKind.FUNCTIONAL, title="Functional specification",
            body=payload.functional_specification, generated_by_role=str(AnalystRole.BA),
            model_id=result.usage.model_id, author_id=actor_id,
        ))
    return counts


async def _create_item(project: Project, item_type: ItemType, parent_id: str | None,
                       title: str, description: str | None, criteria: list[Any], *,
                       actor_id: str, story: Any = None
                       ) -> tuple[BacklogItem, ArtifactVersion]:
    from app.models.backlog import BacklogItemCreate

    item, version = await backlog_service.create_item(
        project.id,
        BacklogItemCreate(type=item_type, parent_id=parent_id, title=title,
                          description=description,
                          actor=getattr(story, "actor", None),
                          need=getattr(story, "need", None),
                          benefit=getattr(story, "benefit", None)),
        actor_id=actor_id, generated_by_role=str(AnalystRole.BA))

    acceptance = [
        AcceptanceCriterion(
            id=f"AC-{item.stable_id}-{index:02d}",
            text=c.text if hasattr(c, "text") else str(c.get("text", "")),
            outcome_level=(c.outcome_level if hasattr(c, "outcome_level")
                           else bool(c.get("outcomeLevel"))),
            provenance=Provenance.AI_SUGGESTION,
        )
        for index, c in enumerate(criteria or [], start=1)
    ]
    changes: dict[str, Any] = {"acceptanceCriteria": [a.model_dump(by_alias=True)
                                                      for a in acceptance],
                               "provenance": str(Provenance.AI_SUGGESTION)}
    if story is not None:
        changes["businessRules"] = list(story.business_rules)
        changes["assumptions"] = list(story.assumptions)
        changes["riskDrivers"] = list(story.risk_drivers)
        changes["citations"] = [c.model_dump(by_alias=True)
                                for c in _citations(story.citations)]
    await artifact_versions.update(version.id, changes)
    version = await artifact_versions.require(version.id)
    return item, version


async def _link_evidence(project_id: str, citations: list[Citation], target_type: str,
                         target_id: str, target_version: int | None = None) -> None:
    for citation in citations:
        await evidence_links.insert(EvidenceLink(
            project_id=project_id,
            source_version_id=citation.locator.source_version_id,
            locator=citation.locator.model_dump(by_alias=True),
            target_type=target_type, target_id=target_id, target_version=target_version,
        ))


# Re-running an analysis must not duplicate what an earlier run created: each
# artifact is skipped when an equivalent one exists, unless the run explicitly
# asks to regenerate. Stable ids continue from the highest number in use, so a
# deleted artifact never causes a collision.

def _next_number(stable_ids: Any, prefix: str) -> int:
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    numbers = [int(match.group(1)) for sid in stable_ids
               if (match := pattern.match(sid or ""))]
    return max(numbers, default=0) + 1


async def _add_specification(request: AnalysisRunRequest, spec: Specification) -> int:
    """Insert a generated specification unless the same one already exists."""
    if not request.regenerate and await specifications.exists({
            "projectId": spec.project_id, "kind": str(spec.kind), "title": spec.title,
            "generatedByRole": spec.generated_by_role}):
        return 0
    await specifications.insert(spec)
    return 1


async def _persist_findings(project: Project, role: AnalystRole, job_id: str,
                            entries: list[Any], request: AnalysisRunRequest) -> int:
    """Review findings of a stage, linked to the backlog item they name.

    A finding still open from an earlier run is not raised twice; one that was
    resolved or waived may be raised again if the problem is still there.
    """
    by_stable = {i.stable_id: i for i in await backlog_items.list({"projectId": project.id})}
    open_already = {
        (f.title, f.target_id)
        for f in await findings.list({"projectId": project.id, "role": str(role),
                                      "status": str(FindingStatus.OPEN)})
    }
    created = 0
    for entry in entries:
        target = by_stable.get(entry.target_stable_id or "")
        key = (entry.title, target.id if target else None)
        if key in open_already and not request.regenerate:
            continue
        open_already.add(key)
        created += 1
        await findings.insert(ReviewFinding(
            project_id=project.id, job_id=job_id, role=role,
            severity=Severity(entry.severity), category=entry.category,
            title=entry.title, rationale=entry.rationale,
            recommendation=entry.recommendation,
            target_type="backlog_item" if target else None,
            target_id=target.id if target else None,
            target_version=target.current_version if target else None,
            blocking=entry.blocking, citations=_citations(entry.citations),
        ))
    return created


async def _persist_requirements(project: Project, role: AnalystRole,
                                kind: RequirementType, prefix: str, entries: list[Any],
                                request: AnalysisRunRequest, *,
                                provenance: Provenance | None = None) -> int:
    """Requirements of one kind with their own stable id series (NFR-, UX-, DATA-)."""
    all_requirements = await requirements.list({"projectId": project.id})
    existing = {r.title.strip().lower() for r in all_requirements if r.type == kind}
    index = _next_number((r.stable_id for r in all_requirements), prefix) - 1
    created = 0
    for entry in entries:
        if entry.title.strip().lower() in existing and not request.regenerate:
            continue
        index += 1
        requirement = Requirement(
            project_id=project.id, stable_id=f"{prefix}-{index:03d}", type=kind,
            title=entry.title, statement=entry.statement, rationale=entry.rationale,
            provenance=provenance or Provenance(entry.provenance),
            priority=Priority(entry.priority) if entry.priority in set(Priority)
            else Priority.MEDIUM,
            confidence=entry.confidence, citations=_citations(entry.citations),
            created_by_role=str(role),
        )
        await requirements.insert(requirement)
        existing.add(entry.title.strip().lower())
        await _link_evidence(project.id, requirement.citations, "requirement", requirement.id)
        created += 1
    return created


async def _persist_ux(project: Project, result: gateway.GatewayResult,
                      request: AnalysisRunRequest, *, actor_id: str,
                      job_id: str) -> dict[str, int]:
    payload: schemas.UXOutput = result.validated
    counts = {
        "findings": await _persist_findings(project, AnalystRole.UX, job_id,
                                            payload.findings, request),
        "uxRequirements": await _persist_requirements(
            project, AnalystRole.UX, RequirementType.UX, "UX", payload.ux_requirements,
            request),
        "specifications": 0,
    }
    if not request.generate_specifications:
        return counts

    if payload.personas or payload.screens:
        lines = ["# UX specification", "",
                 "Personas, screens and states proposed by the UX analyst. Proposals "
                 "need confirmation with real users before design starts.", ""]
        if payload.personas:
            lines += ["## Personas", ""]
            for persona in payload.personas:
                lines.append(f"### {persona.name}")
                lines += [f"- Goal: {goal}" for goal in persona.goals]
                lines += [f"- Pain point: {pain}" for pain in persona.pain_points]
                lines.append("")
        if payload.screens:
            lines += ["## Screens and states", ""]
            for screen in payload.screens:
                stories = ", ".join(screen.story_stable_ids) or "no linked story"
                lines += [f"### {screen.name}", "", f"{screen.purpose} ({stories})", "",
                          "States to design: " + ", ".join(screen.states)]
                lines += [f"- {element}" for element in screen.key_elements]
                lines.append("")
        counts["specifications"] += await _add_specification(request, Specification(
            project_id=project.id, kind=SpecificationKind.UX,
            title="UX specification", body="\n".join(lines).rstrip() + "\n",
            structured={"personas": [x.model_dump(by_alias=True) for x in payload.personas],
                        "screens": [x.model_dump(by_alias=True) for x in payload.screens]},
            generated_by_role=str(AnalystRole.UX), model_id=result.usage.model_id,
            author_id=actor_id))
    for journey in payload.journeys:
        if not journey.mermaid:
            continue
        counts["specifications"] += await _add_specification(request, Specification(
            project_id=project.id, kind=SpecificationKind.PROCESS_DIAGRAM,
            title=journey.title, diagram_source=journey.mermaid,
            structured={"actors": [journey.persona] if journey.persona else [],
                        "requirementIds": journey.story_stable_ids,
                        "steps": journey.steps},
            generated_by_role=str(AnalystRole.UX), model_id=result.usage.model_id,
            author_id=actor_id))
    return counts


async def _persist_data(project: Project, result: gateway.GatewayResult,
                        request: AnalysisRunRequest, *, actor_id: str,
                        job_id: str) -> dict[str, int]:
    payload: schemas.DataOutput = result.validated
    counts = {
        "findings": await _persist_findings(project, AnalystRole.DATA, job_id,
                                            payload.findings, request),
        "dataRequirements": await _persist_requirements(
            project, AnalystRole.DATA, RequirementType.DATA, "DATA",
            payload.data_requirements, request),
        "specifications": 0,
    }
    if not request.generate_specifications:
        return counts
    if not (payload.quality_rules or payload.metrics or payload.retention or payload.migration):
        return counts

    lines = ["# Data specification", "",
             "Data quality, reporting, retention and migration proposed by the data "
             "analyst. Retention periods must be confirmed with their legal basis.", ""]
    if payload.quality_rules:
        lines += ["## Data quality rules", "", "| Entity | Field | Rule | Severity |",
                  "|---|---|---|---|"]
        lines += [f"| {r.entity} | {r.field or '—'} | {r.rule} | {r.severity} |"
                  for r in payload.quality_rules]
        lines.append("")
    if payload.metrics:
        lines += ["## Reporting metrics", ""]
        for metric in payload.metrics:
            lines.append(f"- **{metric.name}**: {metric.definition}"
                         + (f" Formula: `{metric.formula}`." if metric.formula
                            else " Formula: to be agreed."))
        lines.append("")
    if payload.retention:
        lines += ["## Retention and deletion", ""]
        lines += [f"- **{r.entity}** ({r.classification}): {r.retention}"
                  + (f" Deletion: {r.deletion}." if r.deletion else "")
                  for r in payload.retention]
        lines.append("")
    if payload.migration:
        lines += ["## Migration", ""]
        lines += [f"- From {m.source}" + (f" to {m.target}" if m.target else "")
                  + f": {m.notes}" for m in payload.migration]
        lines.append("")
    counts["specifications"] += await _add_specification(request, Specification(
        project_id=project.id, kind=SpecificationKind.DATA,
        title="Data specification", body="\n".join(lines).rstrip() + "\n",
        structured={
            "qualityRules": [x.model_dump(by_alias=True) for x in payload.quality_rules],
            "metrics": [x.model_dump(by_alias=True) for x in payload.metrics],
            "retention": [x.model_dump(by_alias=True) for x in payload.retention],
            "migration": [x.model_dump(by_alias=True) for x in payload.migration],
        },
        generated_by_role=str(AnalystRole.DATA), model_id=result.usage.model_id,
        author_id=actor_id,
        validation={"structural": "rules, metrics and retention validated against the schema",
                    "note": "Retention periods are not legal advice."}))
    return counts


async def _persist_ta(project: Project, result: gateway.GatewayResult,
                      request: AnalysisRunRequest, *, actor_id: str,
                      job_id: str) -> dict[str, int]:
    payload: schemas.TAOutput = result.validated
    counts = {"findings": 0, "nfrRequirements": 0, "dependencies": 0, "specifications": 0}
    items = await backlog_items.list({"projectId": project.id})
    by_stable = {i.stable_id: i for i in items}

    counts["findings"] = await _persist_findings(project, AnalystRole.TA, job_id,
                                                 payload.findings, request)
    # The technical analyst's targets are proposals whatever the model labels them.
    counts["nfrRequirements"] = await _persist_requirements(
        project, AnalystRole.TA, RequirementType.NON_FUNCTIONAL, "NFR",
        payload.nfr_requirements, request, provenance=Provenance.AI_SUGGESTION)

    for dependency in payload.dependencies:
        item = by_stable.get(dependency.get("stableId") or "")
        if not item:
            continue
        if not request.regenerate and await dependency_links.exists({
                "projectId": project.id, "fromId": item.id,
                "toId": dependency.get("stableId", ""), "kind": "requires"}):
            continue
        await dependency_links.insert(DependencyLink(
            project_id=project.id, from_id=item.id,
            to_id=dependency.get("stableId", ""), kind="requires", external=True,
            note=dependency.get("description")))
        counts["dependencies"] += 1

    # Technical notes are merged into the current draft versions.
    for stable_id, note in payload.technical_notes.items():
        item = by_stable.get(stable_id)
        if not item or not item.current_version_id:
            continue
        version = await artifact_versions.get(item.current_version_id)
        if version and version.state != ArtifactState.APPROVED:
            await artifact_versions.update(version.id, {"technicalNotes": note})

    if request.generate_specifications:
        if payload.data_entities:
            counts["specifications"] += await _add_specification(request, Specification(
                project_id=project.id, kind=SpecificationKind.DATA_MODEL,
                title="Proposed data model",
                structured={"entities": [e.model_dump(by_alias=True)
                                         for e in payload.data_entities]},
                generated_by_role=str(AnalystRole.TA), model_id=result.usage.model_id,
                author_id=actor_id,
                validation={"structural": "entities validated against the schema",
                            "note": "Not implemented or runtime tested."}))
        if payload.api_operations:
            counts["specifications"] += await _add_specification(request, Specification(
                project_id=project.id, kind=SpecificationKind.API,
                title="Proposed project API specification",
                structured=_openapi_document(project, payload.api_operations),
                generated_by_role=str(AnalystRole.TA), model_id=result.usage.model_id,
                author_id=actor_id,
                validation={"structural": "OpenAPI 3.1 skeleton validated",
                            "note": "Describes the client's proposed project APIs. "
                                    "It is not an implemented contract."}))
        for diagram in payload.process_diagrams:
            counts["specifications"] += await _add_specification(request, Specification(
                project_id=project.id, kind=SpecificationKind.PROCESS_DIAGRAM,
                title=diagram.get("title", "Process diagram"),
                diagram_source=diagram.get("mermaid"),
                structured={"actors": diagram.get("actors", []),
                            "requirementIds": diagram.get("requirementIds", [])},
                generated_by_role=str(AnalystRole.TA), model_id=result.usage.model_id,
                author_id=actor_id))
        nfr_body = "\n".join(
            f"- **{n.title}** — {n.statement} (verification: review and measurement on the "
            "agreed reference deployment; owner: to be assigned)"
            for n in payload.nfr_requirements)
        if nfr_body:
            counts["specifications"] += await _add_specification(request, Specification(
                project_id=project.id, kind=SpecificationKind.NON_FUNCTIONAL,
                title="Non functional specification",
                body="# Non functional specification\n\n" + nfr_body,
                generated_by_role=str(AnalystRole.TA), model_id=result.usage.model_id,
                author_id=actor_id))
    return counts


def _openapi_document(project: Project, operations: list[Any]) -> dict[str, Any]:
    paths: dict[str, Any] = {}
    for operation in operations:
        entry = paths.setdefault(operation.path, {})
        entry[operation.method.lower()] = {
            "summary": operation.summary,
            "security": [{"bearerAuth": []}],
            "parameters": ([{"name": "limit", "in": "query",
                             "schema": {"type": "integer", "default": 50}},
                            {"name": "offset", "in": "query",
                             "schema": {"type": "integer", "default": 0}}]
                           if operation.paginated else []),
            "requestBody": ({"required": True,
                             "content": {"application/json":
                                         {"schema": operation.request_schema}}}
                            if operation.request_schema else None),
            "responses": {
                "200": {"description": "Success",
                        "content": {"application/json": {"schema": operation.response_schema}}},
                **{str(e.get("status", 400)): {"description": e.get("code", "error")}
                   for e in operation.errors},
            },
        }
        if operation.idempotent:
            entry[operation.method.lower()].setdefault("parameters", []).append(
                {"name": "Idempotency-Key", "in": "header", "required": False,
                 "schema": {"type": "string"}})
        entry[operation.method.lower()] = {
            k: v for k, v in entry[operation.method.lower()].items() if v is not None}
    return {
        "openapi": "3.1.0",
        "info": {"title": f"{project.name} proposed API", "version": "0.1.0",
                 "description": "Generated proposal for the client's project APIs. "
                                "Structurally validated only."},
        "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}},
        "paths": paths,
    }


async def _persist_qa(project: Project, result: gateway.GatewayResult,
                      request: AnalysisRunRequest, *, actor_id: str,
                      job_id: str) -> dict[str, int]:
    payload: schemas.QAOutput = result.validated
    counts = {"findings": 0, "tests": 0}
    items = await backlog_items.list({"projectId": project.id})
    by_stable = {i.stable_id: i for i in items}

    counts["findings"] = await _persist_findings(project, AnalystRole.QA, job_id,
                                                 payload.findings, request)

    if not request.generate_tests:
        return counts

    existing_tests = await test_cases.list({"projectId": project.id})
    written = {(t.story_id, t.title) for t in existing_tests}
    index = _next_number((t.stable_id for t in existing_tests), "TC") - 1
    for test_out in payload.tests:
        story = by_stable.get(test_out.story_stable_id or "")
        key = (story.id if story else None, test_out.title)
        if key in written and not request.regenerate:
            continue
        written.add(key)
        index += 1
        criterion_ids: list[str] = []
        if story and story.current_version_id and test_out.criterion_index is not None:
            version = await artifact_versions.get(story.current_version_id)
            if version and 0 <= test_out.criterion_index < len(version.acceptance_criteria):
                criterion_ids = [version.acceptance_criteria[test_out.criterion_index].id]

        gherkin = _gherkin_feature(test_out, story.stable_id if story else None)
        case = TestCase(
            project_id=project.id, stable_id=f"TC-{index:03d}", title=test_out.title,
            objective=test_out.objective, story_id=story.id if story else None,
            story_version=story.current_version if story else None,
            criterion_ids=criterion_ids,
            test_type=TestType(test_out.test_type) if test_out.test_type in set(TestType)
            else TestType.POSITIVE,
            priority=Priority(test_out.priority) if test_out.priority in set(Priority)
            else Priority.MEDIUM,
            preconditions=test_out.preconditions,
            steps=[TestStep(ordinal=s.get("ordinal", i + 1), action=s.get("action", ""),
                            expected=s.get("expected"))
                   for i, s in enumerate(test_out.steps)],
            expected_results=test_out.expected_results,
            environment_assumptions=test_out.environment_assumptions,
            gherkin=gherkin,
            tags=gherkin.tags if gherkin else [],
            generated_by_role=str(AnalystRole.QA),
            owner_subtree_root=story.path[0] if story and story.path else
            (story.id if story else None),
            validation={"gherkin": "validated" if gherkin else "absent",
                        "note": "Generated tests are drafts; no run status is implied."},
        )
        await test_cases.insert(case)
        counts["tests"] += 1

    # Refined criteria are proposals attached to the draft version, not silent edits.
    for stable_id, texts in payload.refined_criteria.items():
        item = by_stable.get(stable_id)
        if not item or not item.current_version_id:
            continue
        version = await artifact_versions.get(item.current_version_id)
        if not version or version.state == ArtifactState.APPROVED:
            continue
        existing = {c.text for c in version.acceptance_criteria}
        additions = [
            AcceptanceCriterion(id=f"AC-{stable_id}-{len(version.acceptance_criteria) + i + 1:02d}",
                                text=text, provenance=Provenance.AI_SUGGESTION)
            for i, text in enumerate(texts) if text not in existing
        ]
        if additions:
            await artifact_versions.update(version.id, {
                "acceptanceCriteria": [c.model_dump(by_alias=True)
                                       for c in version.acceptance_criteria + additions]})
    return counts


def _gherkin_feature(test_out: Any, story_stable_id: str | None) -> GherkinFeature | None:
    raw = test_out.gherkin
    if not raw:
        return None
    steps: list[GherkinStep] = []
    for keyword, values in (("Given", raw.given), ("When", raw.when), ("Then", raw.then)):
        for position, text in enumerate(values):
            steps.append(GherkinStep(keyword=keyword if position == 0 else "And", text=text))
    tags = list(raw.tags)
    if story_stable_id and f"@{story_stable_id}" not in tags:
        tags.insert(0, f"@{story_stable_id}")
    return GherkinFeature(
        name=raw.feature, tags=tags,
        scenarios=[GherkinScenario(
            name=raw.scenario, tags=tags, outline=bool(raw.examples_rows), steps=steps,
            examples_header=raw.examples_header, examples_rows=raw.examples_rows)],
    )


async def _bound_correction_loop(project: Project, job: AnalysisJob) -> None:
    """Bounded correction cycles; unresolved findings escalate (section 8.2)."""
    blocking = await findings.list({"projectId": project.id, "jobId": job.id,
                                    "blocking": True, "status": "open"})
    cycle = 0
    while blocking and cycle < job.max_cycles:
        cycle += 1
        job.cycles_used = cycle
        # Each cycle records that the finding was reprocessed. Automatic
        # resolution is not claimed; the analyst or approver decides.
        for finding in blocking:
            await findings.update(finding.id, {"cycle": cycle})
        remaining = await findings.list({"projectId": project.id, "jobId": job.id,
                                         "blocking": True, "status": "open"})
        if len(remaining) == len(blocking):
            break
        blocking = remaining
    if blocking:
        for finding in blocking:
            await findings.update(finding.id, {"status": "escalated"})
        job.warnings.append({
            "stage": "orchestrator",
            "message": (f"{len(blocking)} blocking finding(s) were escalated after "
                        f"{cycle} correction cycle(s) rather than reprocessed further."),
        })


async def regenerate_preview(project_id: str, item_id: str) -> dict[str, Any]:
    """Merge preview before regeneration overwrites human edits (section 8.2)."""
    item = await backlog_items.require(item_id, projectId=project_id)
    version = await artifact_versions.require(item.current_version_id or "")
    human_edited = version.author_id is not None and version.generated_by_role is None
    return {
        "itemId": item_id,
        "currentVersion": version.version,
        "humanEdited": human_edited,
        "fields": {
            "title": version.title,
            "description": version.description,
            "acceptanceCriteria": [c.model_dump(by_alias=True)
                                   for c in version.acceptance_criteria],
        },
        "warning": ("Regeneration creates a new draft version. Human edits in the current "
                    "version are preserved in history and must be merged explicitly."),
    }
