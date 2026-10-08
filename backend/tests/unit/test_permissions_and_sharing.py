"""Authorization, project isolation and client sharing (sections 4 and 15)."""
from __future__ import annotations

import pytest

from app.core.errors import Forbidden, ValidationFailed
from app.core.policy import (CLIENT_FORBIDDEN_FIELDS, Permission, Role,
                             is_client_role, permissions_for)
from app.core.security import hash_password
from app.models.approval import ApprovalSubmit
from app.models.backlog import BacklogItemCreate
from app.models.collaboration import (ClientAcceptance, CommentCreate,
                                      CommentVisibility, ShareGrantCreate)
from app.models.common import Classification, ItemType
from app.models.identity import ProjectMember, User
from app.models.project import Project
from app.models.testing import TestCaseCreate
from app.repositories import backlog_items, members, projects, users
from app.services import approvals, backlog as backlog_service, sharing
from app.services import testing as testing_service


def test_client_reviewer_holds_no_project_wide_read_permissions():
    granted = permissions_for([Role.CLIENT_REVIEWER])
    assert granted == {Permission.CLIENT_COMMENT}
    assert Permission.BACKLOG_READ not in granted
    assert Permission.COST_READ not in granted
    assert Permission.SOURCE_READ not in granted
    assert is_client_role([Role.CLIENT_REVIEWER]) is True


def test_system_admin_has_no_implicit_content_access():
    """Section 4 — infrastructure administration is not a project entitlement."""
    granted = permissions_for([Role.SYSTEM_ADMIN])
    assert Permission.ADMIN_SYSTEM in granted
    assert Permission.BACKLOG_READ not in granted
    assert Permission.SOURCE_RAW_READ not in granted


def test_rate_and_cost_fields_are_on_the_client_deny_list():
    for field in ("estimatedCost", "rate", "roleRates", "internalNotes", "aiPrompt",
                  "modelId", "tokenUsage"):
        assert field in CLIENT_FORBIDDEN_FIELDS


async def _approved_story(project, lead_user):
    epic, _ = await backlog_service.create_item(project.id, BacklogItemCreate(
        type=ItemType.EPIC, title="Accounts",
        acceptance_criteria=["Outcome validated"]), actor_id=lead_user.id)
    feature, _ = await backlog_service.create_item(project.id, BacklogItemCreate(
        type=ItemType.FEATURE, parent_id=epic.id, title="Registration",
        acceptance_criteria=["Outcome demonstrated"]), actor_id=lead_user.id)
    story, _ = await backlog_service.create_item(project.id, BacklogItemCreate(
        type=ItemType.STORY, parent_id=feature.id, title="Customer registers",
        description="Internal note: margin is 40 percent",
        acceptance_criteria=["A customer can register with an email address"]),
        actor_id=lead_user.id)
    await testing_service.create_test(project.id, TestCaseCreate(
        title="Registration works", story_id=story.id), actor_id=lead_user.id)

    manifest = await approvals.build_manifest(project, epic.id, actor_id=lead_user.id)
    await approvals.submit(project,
                           ApprovalSubmit(manifest_id=manifest.id,
                                          manifest_hash=manifest.manifest_hash),
                           actor_id=lead_user.id, actor_email=lead_user.email,
                           can_waive=True)
    return epic, story


@pytest.fixture
async def client_user() -> User:
    person = User(email="reviewer@client.example.com", display_name="Client Reviewer",
                  password_hash=hash_password("x"), is_client=True)
    await users.insert(person)
    return person


async def test_sharing_defaults_to_approved_versions_only(project, lead_user,
                                                          client_user):
    epic, story = await _approved_story(project, lead_user)

    draft, _ = await backlog_service.create_item(project.id, BacklogItemCreate(
        type=ItemType.EPIC, title="Unapproved area"), actor_id=lead_user.id)
    with pytest.raises(ValidationFailed):
        await sharing.create_grant(project.id, ShareGrantCreate(
            audience_email=client_user.email, item_ids=[draft.id]),
            actor_id=lead_user.id)

    grant = await sharing.create_grant(project.id, ShareGrantCreate(
        audience_email=client_user.email, item_ids=[story.id],
        allow_acceptance=True), actor_id=lead_user.id)
    assert grant.versions[0]["draft"] is False
    assert grant.versions[0]["version"] == 1


async def test_client_workspace_excludes_internal_fields(project, lead_user,
                                                         client_user):
    _, story = await _approved_story(project, lead_user)
    await sharing.create_grant(project.id, ShareGrantCreate(
        audience_email=client_user.email, item_ids=[story.id],
        allow_acceptance=True), actor_id=lead_user.id)

    workspace = await sharing.client_workspace(client_user, project.id)
    assert len(workspace["items"]) == 1
    shared = workspace["items"][0]
    for forbidden in CLIENT_FORBIDDEN_FIELDS:
        assert forbidden not in shared
    assert workspace["allowAcceptance"] is True


async def test_client_cannot_read_an_unshared_project(project, lead_user, client_user):
    """AT-11 — no grant means no content, not a filtered view."""
    other = Project(key="OTHER", name="Unrelated project")
    await projects.insert(other)
    await _approved_story(project, lead_user)

    with pytest.raises(Forbidden):
        await sharing.client_workspace(client_user, other.id)


async def test_revoked_grant_blocks_future_access(project, lead_user, client_user):
    _, story = await _approved_story(project, lead_user)
    grant = await sharing.create_grant(project.id, ShareGrantCreate(
        audience_email=client_user.email, item_ids=[story.id]), actor_id=lead_user.id)
    await sharing.client_workspace(client_user, project.id)

    await sharing.revoke_grant(project.id, grant.id, actor_id=lead_user.id)
    with pytest.raises(Forbidden):
        await sharing.client_workspace(client_user, project.id)


async def test_client_cannot_accept_items_that_were_not_shared(project, lead_user,
                                                               client_user):
    _, story = await _approved_story(project, lead_user)
    other, _ = await backlog_service.create_item(project.id, BacklogItemCreate(
        type=ItemType.EPIC, title="Not shared"), actor_id=lead_user.id)
    await sharing.create_grant(project.id, ShareGrantCreate(
        audience_email=client_user.email, item_ids=[story.id],
        allow_acceptance=True), actor_id=lead_user.id)

    with pytest.raises(Forbidden):
        await sharing.record_acceptance(client_user, project.id,
                                        ClientAcceptance(item_ids=[other.id]))


async def test_client_acceptance_is_separate_from_internal_approval(project, lead_user,
                                                                    client_user):
    _, story = await _approved_story(project, lead_user)
    await sharing.create_grant(project.id, ShareGrantCreate(
        audience_email=client_user.email, item_ids=[story.id],
        allow_acceptance=True), actor_id=lead_user.id)

    await sharing.record_acceptance(client_user, project.id,
                                    ClientAcceptance(item_ids=[story.id], accepted=True))
    refreshed = await backlog_items.require(story.id)
    assert refreshed.client_accepted is True
    # Internal approval state is untouched by client acceptance.
    assert refreshed.approved_version == 1


async def test_client_cannot_write_internal_comments(project, lead_user, client_user):
    _, story = await _approved_story(project, lead_user)
    with pytest.raises(Forbidden):
        await sharing.add_comment(project.id, CommentCreate(
            target_type="backlog_item", target_id=story.id, body="internal only",
            visibility=CommentVisibility.INTERNAL), author=client_user, is_client=True)

    comment = await sharing.add_comment(project.id, CommentCreate(
        target_type="backlog_item", target_id=story.id, body="Looks good"),
        author=client_user, is_client=True)
    assert comment.visibility == CommentVisibility.CLIENT

    internal = await sharing.add_comment(project.id, CommentCreate(
        target_type="backlog_item", target_id=story.id, body="Check the margin",
        visibility=CommentVisibility.INTERNAL), author=lead_user, is_client=False)
    assert internal.visibility == CommentVisibility.INTERNAL

    visible_to_client = await sharing.list_comments(project.id, story.id, is_client=True)
    assert [c.id for c in visible_to_client] == [comment.id]
