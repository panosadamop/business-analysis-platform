"""Acceptance scenarios for the version bound approval cascade (section 10.2)."""
from __future__ import annotations

import pytest

from app.core.errors import ConflictState, VersionConflict
from app.models.approval import ApprovalSubmit, Decision
from app.models.backlog import BacklogItemCreate, BacklogItemUpdate
from app.models.common import ArtifactState, ItemType
from app.models.testing import TestCaseCreate, TestStep
from app.repositories import approval_events, artifact_versions, backlog_items
from app.services import approvals, backlog as backlog_service
from app.services import testing as testing_service


async def _build_tree(project, actor_id: str):
    """Epic with two features, five stories and a test per story (AT-03)."""
    epic, _ = await backlog_service.create_item(project.id, BacklogItemCreate(
        type=ItemType.EPIC, title="Customer accounts",
        acceptance_criteria=["The account outcome is validated end to end"]),
        actor_id=actor_id)
    stories = []
    for feature_index in range(2):
        feature, _ = await backlog_service.create_item(project.id, BacklogItemCreate(
            type=ItemType.FEATURE, parent_id=epic.id,
            title=f"Feature {feature_index + 1}",
            acceptance_criteria=["The feature outcome is demonstrated"]),
            actor_id=actor_id)
        for story_index in range(3 if feature_index == 0 else 2):
            story, _ = await backlog_service.create_item(project.id, BacklogItemCreate(
                type=ItemType.STORY, parent_id=feature.id,
                title=f"Story {feature_index + 1}.{story_index + 1}",
                acceptance_criteria=["A registered customer can sign in"]),
                actor_id=actor_id)
            await testing_service.create_test(project.id, TestCaseCreate(
                title=f"Verify {story.stable_id}", story_id=story.id,
                steps=[TestStep(ordinal=1, action="sign in", expected="dashboard")],
                expected_results=["dashboard is shown"]), actor_id=actor_id)
            stories.append(story)
    return epic, stories


async def test_parent_approval_cascades_to_exact_descendant_versions(project, lead_user):
    """AT-03 — one human approval approves the exact descendant manifest."""
    epic, stories = await _build_tree(project, lead_user.id)

    manifest = await approvals.build_manifest(project, epic.id, actor_id=lead_user.id)
    assert manifest.counts["epic"] == 1
    assert manifest.counts["feature"] == 2
    assert manifest.counts["story"] == 5
    assert manifest.counts["test_case"] == 5
    assert not manifest.blockers, [b.message for b in manifest.blockers]

    event = await approvals.submit(
        project, ApprovalSubmit(manifest_id=manifest.id,
                                manifest_hash=manifest.manifest_hash),
        actor_id=lead_user.id, actor_email=lead_user.email, can_waive=True)

    assert event.committed is True
    assert event.decision == Decision.APPROVE
    explicit = [e for e in event.entries if not e.inherited]
    inherited = [e for e in event.entries if e.inherited]
    assert len(explicit) == 1 and explicit[0].item_id == epic.id
    assert len(inherited) == 12

    for story in stories:
        refreshed = await backlog_items.require(story.id)
        assert refreshed.approved_version == story.current_version
        assert refreshed.state == ArtifactState.APPROVED
        version = await artifact_versions.require(refreshed.current_version_id)
        # Inherited approvals reference the parent approval event (REQ-APP-05).
        assert version.approval_event_id == event.id
        assert version.inherited_from_event_id == event.id


async def test_change_during_submission_fails_atomically(project, lead_user):
    """AT-04 — a version conflict leaves nothing approved."""
    epic, stories = await _build_tree(project, lead_user.id)
    manifest = await approvals.build_manifest(project, epic.id, actor_id=lead_user.id)

    # A story changes between preview and submission.
    await backlog_service.update_item(project.id, stories[0].id, BacklogItemUpdate(
        description="Edited while the approval was being prepared"),
        actor_id=lead_user.id)

    with pytest.raises(VersionConflict) as error:
        await approvals.submit(
            project, ApprovalSubmit(manifest_id=manifest.id,
                                    manifest_hash=manifest.manifest_hash),
            actor_id=lead_user.id, actor_email=lead_user.email, can_waive=True)

    assert "refreshedManifestId" in error.value.details
    for item in await backlog_items.list({"projectId": project.id}):
        assert item.approved_version is None
    assert await approval_events.count({"projectId": project.id, "committed": True}) == 0


async def test_new_descendant_is_not_covered_by_an_earlier_approval(project, lead_user):
    """AT-05 — a story added after approval stays draft and the parent needs renewal."""
    epic, _ = await _build_tree(project, lead_user.id)
    manifest = await approvals.build_manifest(project, epic.id, actor_id=lead_user.id)
    await approvals.submit(project,
                           ApprovalSubmit(manifest_id=manifest.id,
                                          manifest_hash=manifest.manifest_hash),
                           actor_id=lead_user.id, actor_email=lead_user.email,
                           can_waive=True)

    feature = (await backlog_items.list({"projectId": project.id, "type": "feature"}))[0]
    new_story, _ = await backlog_service.create_item(project.id, BacklogItemCreate(
        type=ItemType.STORY, parent_id=feature.id, title="Late addition",
        acceptance_criteria=["A new observable outcome"]), actor_id=lead_user.id)

    assert (await backlog_items.require(new_story.id)).approved_version is None
    assert (await backlog_items.require(epic.id)).requires_reapproval is True
    assert (await backlog_items.require(feature.id)).requires_reapproval is True


async def test_editing_an_approved_child_creates_a_draft_and_keeps_history(project,
                                                                          lead_user):
    """REQ-APP-06 — approved versions are immutable; edits branch a new draft."""
    epic, stories = await _build_tree(project, lead_user.id)
    manifest = await approvals.build_manifest(project, epic.id, actor_id=lead_user.id)
    await approvals.submit(project,
                           ApprovalSubmit(manifest_id=manifest.id,
                                          manifest_hash=manifest.manifest_hash),
                           actor_id=lead_user.id, actor_email=lead_user.email,
                           can_waive=True)

    story = stories[0]
    approved_version_id = (await backlog_items.require(story.id)).current_version_id
    await backlog_service.update_item(project.id, story.id,
                                      BacklogItemUpdate(description="Refined wording"),
                                      actor_id=lead_user.id)

    refreshed = await backlog_items.require(story.id)
    assert refreshed.current_version == 2
    assert refreshed.state == ArtifactState.DRAFT
    assert refreshed.requires_reapproval is True

    old = await artifact_versions.require(approved_version_id)
    assert old.state == ArtifactState.SUPERSEDED
    assert old.approved_at is not None  # the approved baseline is preserved


async def test_critical_blocker_requires_resolution_or_recorded_waiver(project, lead_user):
    """Section 8.2 — a story with no test cannot be approved without a waiver."""
    epic, _ = await backlog_service.create_item(project.id, BacklogItemCreate(
        type=ItemType.EPIC, title="Untested area",
        acceptance_criteria=["Outcome"]), actor_id=lead_user.id)
    feature, _ = await backlog_service.create_item(project.id, BacklogItemCreate(
        type=ItemType.FEATURE, parent_id=epic.id, title="Feature",
        acceptance_criteria=["Outcome"]), actor_id=lead_user.id)
    story, _ = await backlog_service.create_item(project.id, BacklogItemCreate(
        type=ItemType.STORY, parent_id=feature.id, title="Story without tests",
        acceptance_criteria=["Observable outcome"]), actor_id=lead_user.id)

    manifest = await approvals.build_manifest(project, epic.id, actor_id=lead_user.id)
    kinds = {b.kind for b in manifest.blockers}
    assert "untestable_requirement" in kinds

    with pytest.raises(ConflictState):
        await approvals.submit(project,
                               ApprovalSubmit(manifest_id=manifest.id,
                                              manifest_hash=manifest.manifest_hash),
                               actor_id=lead_user.id, actor_email=lead_user.email,
                               can_waive=True)

    manifest = await approvals.build_manifest(project, epic.id, actor_id=lead_user.id)
    event = await approvals.submit(
        project,
        ApprovalSubmit(manifest_id=manifest.id, manifest_hash=manifest.manifest_hash,
                       waivers=[{"blockerKind": "untestable_requirement",
                                 "targetId": story.id,
                                 "rationale": "Covered by an existing regression suite"}]),
        actor_id=lead_user.id, actor_email=lead_user.email, can_waive=True)
    assert event.committed is True
    assert event.waivers[0].rationale.startswith("Covered by")


async def test_revocation_restores_draft_state_and_requires_reapproval(project, lead_user):
    """REQ-APP-07 — revocation affects the versions it approved."""
    epic, stories = await _build_tree(project, lead_user.id)
    manifest = await approvals.build_manifest(project, epic.id, actor_id=lead_user.id)
    event = await approvals.submit(project,
                                   ApprovalSubmit(manifest_id=manifest.id,
                                                  manifest_hash=manifest.manifest_hash),
                                   actor_id=lead_user.id, actor_email=lead_user.email,
                                   can_waive=True)

    await approvals.revoke(project.id, event.id, reason="Client withdrew the scope",
                           item_ids=[], actor_id=lead_user.id)

    for story in stories:
        refreshed = await backlog_items.require(story.id)
        assert refreshed.approved_version is None
        assert refreshed.requires_reapproval is True
