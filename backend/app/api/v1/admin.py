"""Administration: models, calibration, audit, jobs and egress records."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, ProjectCtx, SystemAdmin
from app.ai import gateway
from app.core.config import settings
from app.core.errors import ConflictState, NotFound, ValidationFailed
from app.core.policy import Permission, Role
from app.core.security import hash_password
from app.models.identity import PublicUser, User
from app.repositories import (audit_events, egress_manifests, jobs, projects,
                              users)
from app.services import audit, calibration
from app.workers import queue

router = APIRouter(tags=["admin"], prefix="/admin")


@router.get("/models")
async def model_health(user: SystemAdmin) -> dict[str, Any]:
    return {
        "adapters": await gateway.health_report(),
        "configuration": {
            "defaultLocalModel": settings.default_local_model,
            "localInferenceUrl": settings.local_inference_url,
            "cloudProvider": settings.cloud_provider,
            "cloudEnabledGlobally": settings.cloud_enabled_globally,
            "cloudModel": settings.cloud_model if settings.cloud_enabled_globally else None,
            "monthlyBudgetEur": settings.ai_monthly_budget_eur,
        },
        "note": ("Cloud is disabled by default. A project may be stricter than the "
                 "deployment, never looser."),
    }


@router.get("/users", response_model=list[PublicUser])
async def list_users(user: SystemAdmin, limit: int = Query(100, le=500)
                     ) -> list[PublicUser]:
    rows = await users.list({}, sort=[("createdAt", -1)], limit=limit)
    return [PublicUser(id=u.id, email=u.email, display_name=u.display_name,
                       global_roles=u.global_roles, is_client=u.is_client,
                       locale=u.locale, active=u.active) for u in rows]


@router.post("/users", response_model=PublicUser, status_code=201)
async def create_user(body: dict[str, Any], admin: SystemAdmin) -> PublicUser:
    email = body["email"].lower()
    if await users.exists({"email": email}):
        raise ConflictState("An account with that email already exists")
    roles = [str(role) for role in body.get("globalRoles", [])]
    unknown = [role for role in roles if role not in set(Role)]
    if unknown:
        raise ValidationFailed("Unknown platform role", details={"unknown": unknown})

    person = User(email=email, display_name=body["displayName"],
                  password_hash=hash_password(body["password"]),
                  global_roles=roles, is_client=body.get("isClient", False))
    await users.insert(person)
    await audit.record("admin.user_created", actor_id=admin.id,
                       actor_email=admin.email, object_type="user",
                       object_id=person.id,
                       detail={"email": email, "globalRoles": roles})
    return _public(person)


def _public(person: User) -> PublicUser:
    return PublicUser(id=person.id, email=person.email,
                      display_name=person.display_name,
                      global_roles=person.global_roles, is_client=person.is_client,
                      locale=person.locale, active=person.active)


@router.patch("/users/{user_id}", response_model=PublicUser)
async def update_user(user_id: str, body: dict[str, Any], admin: SystemAdmin
                      ) -> PublicUser:
    """Change a person's platform roles or disable the account.

    Granting ``superuser`` hands over ownership of every project, so the change
    is recorded against the administrator who made it.
    """
    person = await users.get(user_id)
    if not person:
        raise NotFound("Account not found")

    changes: dict[str, Any] = {}
    if "globalRoles" in body:
        roles = [str(role) for role in body["globalRoles"]]
        unknown = [role for role in roles if role not in set(Role)]
        if unknown:
            raise ValidationFailed("Unknown platform role",
                                   details={"unknown": unknown})
        changes["globalRoles"] = roles
    if "active" in body:
        changes["active"] = bool(body["active"])
    if "displayName" in body:
        changes["displayName"] = body["displayName"]
    if not changes:
        return _public(person)

    # The deployment must never be left without an owner.
    new_roles = changes.get("globalRoles")
    giving_up_ownership = (
        new_roles is not None
        and str(Role.SUPERUSER) in person.global_roles
        and str(Role.SUPERUSER) not in new_roles
    )
    disabling_owner = (changes.get("active") is False
                       and str(Role.SUPERUSER) in person.global_roles)
    if giving_up_ownership or disabling_owner:
        remaining = await users.count({"globalRoles": str(Role.SUPERUSER),
                                       "active": True})
        if remaining <= 1:
            raise ConflictState(
                "This is the only active platform owner; grant the role to "
                "someone else before taking it away")

    updated = await users.update(user_id, changes)
    await audit.record("admin.user_updated", actor_id=admin.id,
                       actor_email=admin.email, object_type="user",
                       object_id=user_id,
                       detail={"fields": sorted(changes),
                               "grantedSuperuser": str(Role.SUPERUSER)
                               in changes.get("globalRoles", [])})
    return _public(updated)


@router.get("/jobs")
async def list_jobs(user: SystemAdmin, status: str | None = Query(None),
                    limit: int = Query(50, le=200)) -> list[dict[str, Any]]:
    query: dict[str, Any] = {}
    if status:
        query["status"] = status
    rows = await jobs.list(query, sort=[("createdAt", -1)], limit=limit)
    return [{"id": j.id, "kind": j.kind, "status": str(j.status),
             "projectId": j.project_id, "attempts": j.attempts,
             "progress": j.progress, "message": j.message, "error": j.error,
             "createdAt": j.created_at, "finishedAt": j.finished_at} for j in rows]


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, user: SystemAdmin) -> dict[str, Any]:
    record = await queue.cancel(job_id)
    return {"id": record.id, "cancelRequested": record.cancel_requested}


@router.get("/calibration")
async def list_calibrations(user: SystemAdmin) -> list[dict[str, Any]]:
    rows = await calibration.list_versions()
    return [r.model_dump(by_alias=True) for r in rows]


@router.post("/calibration/candidates")
async def build_candidate(body: dict[str, Any], admin: SystemAdmin) -> dict[str, Any]:
    """Offline candidate build with a time separated holdout evaluation."""
    version = await calibration.build_candidate(
        actor_id=admin.id, project_ids=body.get("projectIds"), note=body.get("note"))
    return version.model_dump(by_alias=True)


@router.post("/calibration/{version_id}/activate")
async def activate_calibration(version_id: str, admin: SystemAdmin) -> dict[str, Any]:
    version = await calibration.activate(version_id, actor_id=admin.id)
    return version.model_dump(by_alias=True)


@router.post("/calibration/{version_id}/rollback")
async def rollback_calibration(version_id: str, admin: SystemAdmin) -> dict[str, str]:
    await calibration.rollback(version_id, actor_id=admin.id)
    return {"status": "rolled_back"}


project_admin = APIRouter(tags=["admin"], prefix="/projects/{project_id}")


@project_admin.get("/audit")
async def project_audit(project_id: str, ctx: ProjectCtx,
                        object_id: str | None = Query(None),
                        limit: int = Query(100, le=500)) -> list[dict[str, Any]]:
    ctx.require(Permission.AUDIT_READ)
    rows = await audit_events.list(
        {"projectId": project_id, **({"objectId": object_id} if object_id else {})},
        sort=[("at", -1)], limit=limit)
    return [r.model_dump(by_alias=True) for r in rows]


@project_admin.get("/egress")
async def egress_log(project_id: str, ctx: ProjectCtx,
                     limit: int = Query(100, le=500)) -> list[dict[str, Any]]:
    """What left company infrastructure, and what was blocked (section 8.3)."""
    ctx.require(Permission.AUDIT_READ)
    rows = await egress_manifests.list({"projectId": project_id}, sort=[("at", -1)],
                                       limit=limit)
    return [r.model_dump(by_alias=True) for r in rows]


@project_admin.get("/jobs")
async def project_jobs(project_id: str, ctx: ProjectCtx,
                       limit: int = Query(50, le=200)) -> list[dict[str, Any]]:
    ctx.require(Permission.ANALYSIS_READ)
    rows = await jobs.list({"projectId": project_id}, sort=[("createdAt", -1)],
                           limit=limit)
    return [{"id": j.id, "kind": j.kind, "status": str(j.status),
             "progress": j.progress, "message": j.message, "error": j.error,
             "createdAt": j.created_at, "finishedAt": j.finished_at} for j in rows]
