"""Project, membership and policy endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import (CurrentUser, ProjectContext, ProjectCtx,
                          requires)
from app.core.errors import ConflictState, Forbidden, NotFound
from app.core.policy import Permission, Role, is_platform_admin
from app.core.security import hash_password
from app.core.utils import new_id, utcnow
from app.models.common import Money
from app.models.identity import (MemberCreate, MemberUpdate, MemberView,
                                 ProjectMember, User)
from app.models.project import (Project, ProjectCreate, ProjectHealth,
                                ProjectUpdate)
from app.repositories import (backlog_items, findings, integrations, milestones,
                              members, projects, questions, users, worklogs)
from app.services import approvals, audit
from app.services.estimation import actual_hours, cost_summary

router = APIRouter(tags=["projects"])


@router.get("/projects", response_model=list[ProjectHealth])
async def list_projects(user: CurrentUser,
                        include_archived: bool = Query(False)) -> list[ProjectHealth]:
    """Portfolio view. Only projects the caller is entitled to are returned."""
    if is_platform_admin(user.global_roles):
        # The platform owner and the system administrator see the whole estate.
        rows = await projects.list({} if include_archived else {"archived": False},
                                   sort=[("createdAt", -1)])
    else:
        memberships = await members.list({"userId": user.id, "revokedAt": None})
        ids = [m.project_id for m in memberships]
        if not ids:
            return []
        query: dict[str, Any] = {"_id": {"$in": ids}}
        if not include_archived:
            query["archived"] = False
        rows = await projects.list(query, sort=[("createdAt", -1)])

    result: list[ProjectHealth] = []
    for project in rows:
        result.append(await _health(project))
    return result


async def _health(project: Project) -> ProjectHealth:
    stories = await backlog_items.count({"projectId": project.id, "type": "story"})
    approved = await backlog_items.count({"projectId": project.id, "type": "story",
                                          "approvedVersion": {"$ne": None}})
    critical_questions = await questions.count({"projectId": project.id,
                                                "status": "open",
                                                "severity": "critical"})
    unresolved = await findings.count({"projectId": project.id, "status": "open"})
    pending = await approvals.pending_count(project.id)
    next_milestone = await milestones.list({"projectId": project.id,
                                            "status": "planned"},
                                           sort=[("dueDate", 1)], limit=1)
    connector = await integrations.find_one({"projectId": project.id, "isPrimary": True})
    summary = await cost_summary(project.id, currency=project.currency,
                                 hours_per_person_day=project.calendar.hours_per_person_day)
    return ProjectHealth(
        project_id=project.id, key=project.key, name=project.name,
        client_name=project.client_name, delivery_method=str(project.delivery_method),
        open_critical_questions=critical_questions, pending_approvals=pending,
        unresolved_findings=unresolved, stories=stories, approved_stories=approved,
        estimated_hours=await _estimated_hours(project.id),
        actual_hours=await actual_hours(project.id),
        budget=summary.baseline_budget,
        forecast_cost=summary.forecast_at_completion,
        next_milestone=next_milestone[0].name if next_milestone else None,
        next_milestone_date=None,
        connector_health=connector.health if connector else "not_configured",
        local_only=project.ai_policy.local_only,
    )


async def _estimated_hours(project_id: str) -> float:
    from app.repositories import estimates
    from app.services.estimation import total_hours

    rows = await estimates.list({"projectId": project_id, "superseded": False,
                                 "isRoughParent": False})
    return round(sum(total_hours(e) for e in rows), 2)


@router.post("/projects", response_model=Project, status_code=201)
async def create_project(payload: ProjectCreate, user: CurrentUser) -> Project:
    if user.is_client:
        raise Forbidden("Client accounts cannot create projects")
    if await projects.exists({"key": payload.key.upper()}):
        raise ConflictState("A project with this key already exists")
    project = Project(
        key=payload.key.upper(), name=payload.name, client_name=payload.client_name,
        description=payload.description, languages=payload.languages,
        output_language=payload.output_language, delivery_method=payload.delivery_method,
        default_classification=payload.default_classification, currency=payload.currency,
        enabled_analysts=payload.enabled_analysts, owner_id=user.id,
    )
    if payload.calendar:
        project.calendar = payload.calendar
    if payload.ai_policy:
        project.ai_policy = payload.ai_policy
    await projects.insert(project)
    await members.insert(ProjectMember(project_id=project.id, user_id=user.id,
                                       roles=[str(Role.PROJECT_ADMIN)],
                                       invited_by=user.id))
    await audit.record("project.created", project_id=project.id, actor_id=user.id,
                       actor_email=user.email, object_type="project",
                       object_id=project.id, detail={"key": project.key})
    return project


@router.get("/projects/{project_id}", response_model=Project)
async def get_project(ctx: ProjectCtx) -> Project:
    if ctx.is_client:
        raise Forbidden("Client access runs through the shared workspace")
    if ctx.via_superuser:
        # Reaching a project you are not a member of is worth recording.
        await audit.record("project.accessed_as_owner", project_id=ctx.project.id,
                           actor_id=ctx.user.id, actor_email=ctx.user.email,
                           object_type="project", object_id=ctx.project.id,
                           detail={"standing": "superuser"})
    return ctx.project


@router.patch("/projects/{project_id}", response_model=Project)
async def update_project(project_id: str, payload: ProjectUpdate,
                         ctx: ProjectContext = requires(Permission.PROJECT_MANAGE)) -> Project:
    changes = payload.model_dump(exclude_unset=True, by_alias=True, exclude_none=True)
    if "aiPolicy" in changes:
        ctx.require(Permission.POLICY_MANAGE)
    updated = await projects.update(project_id, changes)
    await audit.record("project.updated", project_id=project_id, actor_id=ctx.user.id,
                       object_type="project", object_id=project_id,
                       detail={"fields": sorted(changes)})
    return updated


@router.get("/projects/{project_id}/members", response_model=list[MemberView])
async def list_members(ctx: ProjectCtx) -> list[MemberView]:
    rows = await members.list({"projectId": ctx.project.id})
    people = {u.id: u for u in await users.list({"_id": {"$in": [m.user_id for m in rows]}})}
    out: list[MemberView] = []
    for member in rows:
        person = people.get(member.user_id)
        if not person:
            continue
        out.append(MemberView(
            id=member.id, user_id=member.user_id, email=person.email,
            display_name=person.display_name, roles=member.roles,
            delivery_role=member.delivery_role,
            allocation_percent=member.allocation_percent,
            acceptance_authority=member.acceptance_authority,
            expires_at=member.expires_at, revoked_at=member.revoked_at))
    return out


@router.post("/projects/{project_id}/members", response_model=MemberView, status_code=201)
async def add_member(project_id: str, payload: MemberCreate,
                     ctx: ProjectContext = requires(Permission.MEMBER_MANAGE)) -> MemberView:
    email = payload.email.lower()
    person = await users.find_one({"email": email})
    if not person:
        is_client = str(Role.CLIENT_REVIEWER) in payload.roles
        person = User(email=email, display_name=payload.display_name or email,
                      is_client=is_client,
                      password_hash=hash_password(new_id()))
        await users.insert(person)
    if await members.exists({"projectId": project_id, "userId": person.id}):
        raise ConflictState("This person is already a member of the project")

    member = ProjectMember(
        project_id=project_id, user_id=person.id, roles=payload.roles,
        delivery_role=payload.delivery_role,
        allocation_percent=payload.allocation_percent,
        acceptance_authority=payload.acceptance_authority,
        expires_at=payload.expires_at, invited_by=ctx.user.id)
    await members.insert(member)
    await audit.record("project.member_added", project_id=project_id, actor_id=ctx.user.id,
                       object_type="projectMember", object_id=member.id,
                       detail={"email": email, "roles": payload.roles})
    return MemberView(id=member.id, user_id=person.id, email=person.email,
                      display_name=person.display_name, roles=member.roles,
                      delivery_role=member.delivery_role,
                      allocation_percent=member.allocation_percent,
                      acceptance_authority=member.acceptance_authority,
                      expires_at=member.expires_at)


@router.patch("/projects/{project_id}/members/{member_id}", response_model=MemberView)
async def update_member(project_id: str, member_id: str, payload: MemberUpdate,
                        ctx: ProjectContext = requires(Permission.MEMBER_MANAGE)) -> MemberView:
    member = await members.get(member_id, projectId=project_id)
    if not member:
        raise NotFound("Member not found")
    changes = payload.model_dump(exclude_unset=True, by_alias=True, exclude_none=True)
    revoked = changes.pop("revoked", None)
    if revoked is True:
        changes["revokedAt"] = utcnow()
    elif revoked is False:
        changes["revokedAt"] = None
    updated = await members.update(member_id, changes)
    person = await users.require(updated.user_id)
    await audit.record("project.member_updated", project_id=project_id,
                       actor_id=ctx.user.id, object_type="projectMember",
                       object_id=member_id, detail={"fields": sorted(changes)})
    return MemberView(id=updated.id, user_id=person.id, email=person.email,
                      display_name=person.display_name, roles=updated.roles,
                      delivery_role=updated.delivery_role,
                      allocation_percent=updated.allocation_percent,
                      acceptance_authority=updated.acceptance_authority,
                      expires_at=updated.expires_at, revoked_at=updated.revoked_at)


@router.get("/projects/{project_id}/health", response_model=ProjectHealth)
async def project_health(ctx: ProjectCtx) -> ProjectHealth:
    ctx.require(Permission.BACKLOG_READ)
    return await _health(ctx.project)


@router.get("/projects/{project_id}/policy")
async def ai_policy(ctx: ProjectCtx) -> dict[str, Any]:
    """What the current data policy actually permits, in plain terms."""
    from app.ai import gateway

    policy = ctx.project.ai_policy
    return {
        "policy": policy.model_dump(by_alias=True),
        "effective": await gateway.health_report(ctx.project),
        "explanation": [
            "Cloud AI cannot analyse company content without receiving some content. "
            "Keeping original files locally does not mean zero disclosure.",
            "Local only mode blocks every project derived cloud payload.",
            "Sanitisation reduces disclosure. It is not a guarantee of anonymisation.",
            "Transcription, OCR, embeddings and source indexing are local by default.",
        ],
    }
