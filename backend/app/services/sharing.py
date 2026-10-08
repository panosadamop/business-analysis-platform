"""Client collaboration (section 15).

A client sees exactly the versions a non expired, non revoked grant lists and
nothing else. Source files, recordings, internal risk notes, financial rates and
AI diagnostics are excluded unless the grant deliberately allows them. Revocation
prevents future access; it cannot recall files that were already downloaded.
"""
from __future__ import annotations

from typing import Any

from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.policy import CLIENT_FORBIDDEN_FIELDS
from app.core.utils import as_utc, utcnow
from app.models.collaboration import (ClientAcceptance, Comment, CommentCreate,
                                      CommentVisibility, ShareGrant,
                                      ShareGrantCreate)
from app.models.common import ArtifactState
from app.models.identity import User
from app.repositories import (artifact_versions, backlog_items, comments,
                              questions, share_grants, specifications,
                              test_cases, users)
from app.services import audit


async def create_grant(project_id: str, payload: ShareGrantCreate, *,
                       actor_id: str) -> ShareGrant:
    items = await backlog_items.list({"projectId": project_id,
                                      "_id": {"$in": payload.item_ids}})
    if len(items) != len(set(payload.item_ids)):
        raise NotFound("One or more selected items do not exist in this project")

    versions: list[dict[str, Any]] = []
    draft_titles: list[str] = []
    for item in items:
        # Sharing defaults to immutable approved versions.
        version_number = item.approved_version
        if version_number is None:
            if not payload.include_drafts:
                raise ValidationFailed(
                    f"{item.stable_id} has no approved version. Enable draft sharing "
                    "explicitly if an unapproved version must be shared.",
                    details={"itemId": item.id})
            version_number = item.current_version
            draft_titles.append(item.stable_id)
        versions.append({"itemId": item.id, "stableId": item.stable_id,
                         "version": version_number,
                         "draft": item.approved_version is None})

    audience = await users.find_one({"email": payload.audience_email})
    grant = ShareGrant(
        project_id=project_id, audience_user_id=audience.id if audience else None,
        audience_email=payload.audience_email, label=payload.label, versions=versions,
        include_drafts=payload.include_drafts, include_questions=payload.include_questions,
        include_progress_report=payload.include_progress_report,
        include_tests=payload.include_tests, include_sources=payload.include_sources,
        allow_download=payload.allow_download, allow_acceptance=payload.allow_acceptance,
        expires_at=payload.expires_at, created_by=actor_id,
    )
    await share_grants.insert(grant)
    await audit.record("share.granted", project_id=project_id, actor_id=actor_id,
                       object_type="shareGrant", object_id=grant.id,
                       detail={"audience": payload.audience_email,
                               "versions": len(versions),
                               "draftsIncluded": draft_titles,
                               "sourcesIncluded": payload.include_sources})
    return grant


async def revoke_grant(project_id: str, grant_id: str, *, actor_id: str) -> ShareGrant:
    grant = await share_grants.require(grant_id, projectId=project_id)
    if grant.revoked_at:
        return grant
    updated = await share_grants.update(grant_id, {"revokedAt": utcnow(),
                                                   "revokedBy": actor_id})
    await audit.record("share.revoked", project_id=project_id, actor_id=actor_id,
                       object_type="shareGrant", object_id=grant_id,
                       detail={"note": "Revocation prevents future access. Files already "
                                       "downloaded cannot be recalled."})
    return updated


async def active_grants_for(user: User, project_id: str | None = None) -> list[ShareGrant]:
    query: dict[str, Any] = {
        "revokedAt": None,
        "$or": [{"audienceUserId": user.id}, {"audienceEmail": user.email}],
    }
    if project_id:
        query["projectId"] = project_id
    now = utcnow()
    return [g for g in await share_grants.list(query)
            if g.expires_at is None or as_utc(g.expires_at) > now]


def _strip_internal(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove internal only fields, including values derived from hidden costs."""
    return {k: v for k, v in payload.items() if k not in CLIENT_FORBIDDEN_FIELDS}


async def client_workspace(user: User, project_id: str) -> dict[str, Any]:
    grants = await active_grants_for(user, project_id)
    if not grants:
        raise Forbidden("No active share grant gives you access to this project")

    allowed: dict[str, int] = {}
    allow_acceptance = False
    include_questions = False
    include_tests = False
    allow_download = False
    for grant in grants:
        allow_acceptance = allow_acceptance or grant.allow_acceptance
        include_questions = include_questions or grant.include_questions
        include_tests = include_tests or grant.include_tests
        allow_download = allow_download or grant.allow_download
        for entry in grant.versions:
            allowed[entry["itemId"]] = max(allowed.get(entry["itemId"], 0),
                                           entry["version"])
        grant.access_log.append({"at": utcnow(), "userId": user.id})
        await share_grants.update(grant.id, {"accessLog": grant.access_log[-50:]})

    items = await backlog_items.list({"projectId": project_id,
                                      "_id": {"$in": list(allowed)}})
    versions = await artifact_versions.list(
        {"itemId": {"$in": list(allowed)}})
    by_key = {(v.item_id, v.version): v for v in versions}

    shared_items: list[dict[str, Any]] = []
    for item in items:
        version = by_key.get((item.id, allowed[item.id]))
        if not version:
            continue
        shared_items.append(_strip_internal({
            "id": item.id, "stableId": item.stable_id, "type": str(item.type),
            "title": version.title, "description": version.description,
            "version": version.version, "state": str(version.state),
            "isDraft": version.state != ArtifactState.APPROVED,
            "acceptanceCriteria": [{"id": c.id, "text": c.text}
                                   for c in version.acceptance_criteria],
            "businessRules": version.business_rules,
            "assumptions": version.assumptions,
            "clientAccepted": item.client_accepted,
            "acceptedAt": item.client_accepted_at,
        }))

    shared_questions = []
    if include_questions:
        shared_questions = [
            {"id": q.id, "stableId": q.stable_id, "title": q.title, "detail": q.detail,
             "severity": str(q.severity), "status": str(q.status)}
            for q in await questions.list({"projectId": project_id,
                                           "clientVisible": True})
        ]

    shared_tests = []
    if include_tests:
        shared_tests = [
            {"id": t.id, "stableId": t.stable_id, "title": t.title,
             "testType": str(t.test_type), "state": str(t.state)}
            for t in await test_cases.list({"projectId": project_id,
                                            "storyId": {"$in": list(allowed)}})
        ]

    shared_specs = [
        {"id": s.id, "title": s.title, "kind": str(s.kind), "body": s.body,
         "diagramSource": s.diagram_source, "version": s.version}
        for s in await specifications.list({"projectId": project_id,
                                            "state": str(ArtifactState.APPROVED)})
    ]

    return {
        "projectId": project_id,
        "items": shared_items,
        "questions": shared_questions,
        "tests": shared_tests,
        "specifications": shared_specs,
        "allowAcceptance": allow_acceptance,
        "allowDownload": allow_download,
        "includesDrafts": any(i["isDraft"] for i in shared_items),
        "note": ("You are viewing versions explicitly shared with you. Internal notes, "
                 "rates, evidence files and AI diagnostics are not included."),
    }


async def record_acceptance(user: User, project_id: str,
                            payload: ClientAcceptance) -> dict[str, Any]:
    grants = await active_grants_for(user, project_id)
    if not any(g.allow_acceptance for g in grants):
        raise Forbidden("This project has not granted you acceptance authority")
    allowed = {entry["itemId"] for g in grants for entry in g.versions
               if g.allow_acceptance}
    unauthorized = [i for i in payload.item_ids if i not in allowed]
    if unauthorized:
        raise Forbidden("Some items were not shared with you",
                        details={"itemIds": unauthorized})

    for item_id in payload.item_ids:
        await backlog_items.update(item_id, {
            "clientAccepted": payload.accepted,
            "clientAcceptedAt": utcnow() if payload.accepted else None},
            projectId=project_id)
    if payload.note:
        await comments.insert(Comment(
            project_id=project_id, target_type="acceptance",
            target_id=",".join(payload.item_ids), body=payload.note,
            author_id=user.id, visibility=CommentVisibility.CLIENT))

    await audit.record("client.acceptance", project_id=project_id, actor_id=user.id,
                       actor_email=user.email, object_type="backlogItem",
                       detail={"accepted": payload.accepted,
                               "items": payload.item_ids,
                               "note": ("Business acceptance is recorded separately "
                                        "from internal readiness approval.")})
    return {"accepted": payload.accepted, "items": payload.item_ids}


async def add_comment(project_id: str, payload: CommentCreate, *, author: User,
                      is_client: bool) -> Comment:
    if is_client and "visibility" in payload.model_fields_set             and payload.visibility == CommentVisibility.INTERNAL:
        # An explicit attempt is refused; an omitted value simply defaults to a
        # client visible comment.
        raise Forbidden("Client users cannot create internal comments")
    comment = Comment(
        project_id=project_id, target_type=payload.target_type,
        target_id=payload.target_id, target_version=payload.target_version,
        body=payload.body, author_id=author.id,
        visibility=CommentVisibility.CLIENT if is_client else payload.visibility,
        requested_change=payload.requested_change, parent_id=payload.parent_id,
    )
    await comments.insert(comment)
    return comment


async def list_comments(project_id: str, target_id: str, *,
                        is_client: bool) -> list[Comment]:
    query: dict[str, Any] = {"projectId": project_id, "targetId": target_id}
    if is_client:
        query["visibility"] = str(CommentVisibility.CLIENT)
    return await comments.list(query, sort=[("createdAt", 1)])
