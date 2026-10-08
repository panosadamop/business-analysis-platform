"""Connector discovery, publication and bidirectional synchronisation
(section 14)."""
from __future__ import annotations

import pytest

from app.core.errors import ConflictState, Forbidden
from app.models.approval import ApprovalSubmit
from app.models.backlog import BacklogItemCreate
from app.models.common import ExecutionStatus, ItemType, JobStatus
from app.models.integration import (ExternalMapping, IntegrationCreate,
                                    IntegrationUpdate, Provider, PublishRequest)
from app.models.testing import TestCaseCreate
from app.repositories import (backlog_items, change_requests, external_mappings,
                              integrations, outbox, sync_events)
from app.services import approvals, backlog as backlog_service
from app.services import integrations as service
from app.services import testing as testing_service


async def _approved_epic(project, lead_user):
    epic, _ = await backlog_service.create_item(project.id, BacklogItemCreate(
        type=ItemType.EPIC, title="Accounts", acceptance_criteria=["Outcome"]),
        actor_id=lead_user.id)
    feature, _ = await backlog_service.create_item(project.id, BacklogItemCreate(
        type=ItemType.FEATURE, parent_id=epic.id, title="Registration",
        acceptance_criteria=["Outcome"]), actor_id=lead_user.id)
    story, _ = await backlog_service.create_item(project.id, BacklogItemCreate(
        type=ItemType.STORY, parent_id=feature.id, title="Customer registers",
        acceptance_criteria=["A customer can register"]), actor_id=lead_user.id)
    await testing_service.create_test(project.id, TestCaseCreate(
        title="Registration works", story_id=story.id), actor_id=lead_user.id)
    manifest = await approvals.build_manifest(project, epic.id, actor_id=lead_user.id)
    event = await approvals.submit(
        project, ApprovalSubmit(manifest_id=manifest.id,
                                manifest_hash=manifest.manifest_hash),
        actor_id=lead_user.id, actor_email=lead_user.email, can_waive=True)
    return epic, story, event


async def _configured(project, lead_user, provider=Provider.JIRA):
    integration = await service.create(project.id, IntegrationCreate(
        provider=provider, name=f"{provider} destination",
        external_project_key="PORTAL"), actor_id=lead_user.id)
    integration = await service.discover(project.id, integration.id,
                                         actor_id=lead_user.id)
    integration = await service.update(project.id, integration.id,
                                       IntegrationUpdate(enabled=True, is_primary=True),
                                       actor_id=lead_user.id)
    return integration


async def test_discovery_reports_limitations_before_any_mapping(project, lead_user):
    """Section 14.1 — no mapping is assumed; the report says what is unknown."""
    integration = await _configured(project, lead_user)
    report = integration.capability_report
    assert report is not None
    assert integration.mapping_approved is False
    assert any("documented" in limitation for limitation in report.limitations)
    assert any("no guaranteed native level" in limitation.lower()
               for limitation in report.limitations)
    feature_mapping = next(t for t in integration.type_mappings
                           if t.canonical_type == "feature")
    assert feature_mapping.strategy in ("link", "metadata")


async def test_asana_discovery_states_the_hierarchy_difference(project, lead_user):
    integration = await _configured(project, lead_user, Provider.ASANA)
    assert any("no native epic" in limitation.lower()
               for limitation in integration.capability_report.limitations)
    assert integration.capability_report.supports_worklogs is False


async def test_publication_requires_approved_mapping_and_approval(project, lead_user):
    epic, story, event = await _approved_epic(project, lead_user)
    integration = await _configured(project, lead_user)

    with pytest.raises(ConflictState):
        await service.enqueue_publication(
            project.id, integration.id,
            PublishRequest(approval_event_id=event.id), actor_id=lead_user.id)

    await service.approve_mapping(project.id, integration.id, actor_id=lead_user.id)
    job = await service.enqueue_publication(
        project.id, integration.id, PublishRequest(approval_event_id=event.id),
        actor_id=lead_user.id)
    assert job.status == JobStatus.QUEUED


async def test_revoked_approval_cannot_be_published(project, lead_user):
    epic, story, event = await _approved_epic(project, lead_user)
    integration = await _configured(project, lead_user)
    await service.approve_mapping(project.id, integration.id, actor_id=lead_user.id)
    await approvals.revoke(project.id, event.id, reason="withdrawn", item_ids=[],
                           actor_id=lead_user.id)

    with pytest.raises(Forbidden):
        await service.enqueue_publication(
            project.id, integration.id, PublishRequest(approval_event_id=event.id),
            actor_id=lead_user.id)


async def test_replayed_publication_request_is_idempotent(project, lead_user):
    """AT-08 — the same job is returned, not a duplicate."""
    epic, story, event = await _approved_epic(project, lead_user)
    integration = await _configured(project, lead_user)
    await service.approve_mapping(project.id, integration.id, actor_id=lead_user.id)

    first = await service.enqueue_publication(
        project.id, integration.id,
        PublishRequest(approval_event_id=event.id, idempotency_key="publish-1"),
        actor_id=lead_user.id)
    second = await service.enqueue_publication(
        project.id, integration.id,
        PublishRequest(approval_event_id=event.id, idempotency_key="publish-1"),
        actor_id=lead_user.id)
    assert first.id == second.id
    assert await outbox.count({"projectId": project.id}) == 1


async def test_publication_preview_shows_unsupported_fields(project, lead_user):
    epic, story, event = await _approved_epic(project, lead_user)
    integration = await _configured(project, lead_user)
    preview = await service.publication_preview(project.id, integration.id, event.id)

    assert preview.total >= 3
    assert preview.hierarchy_note
    row = next(r for r in preview.rows if r.canonical_type == "story")
    assert "acceptanceCriteria" in row.unsupported_fields
    assert preview.information_loss is True


async def test_replayed_webhook_event_is_ignored(project, lead_user):
    """AT-08 — a repeated event id applies nothing a second time."""
    epic, story, event = await _approved_epic(project, lead_user)
    integration = await _configured(project, lead_user)
    await external_mappings.insert(ExternalMapping(
        project_id=project.id, integration_id=integration.id, internal_id=story.id,
        internal_type="story", external_id="EXT-1",
        last_common_values={"executionStatus": "not_started"}))

    first = await service.ingest_remote_change(
        project.id, integration.id, event_id="evt-1", external_id="EXT-1",
        fields={"status": {"name": "In Progress"}})
    second = await service.ingest_remote_change(
        project.id, integration.id, event_id="evt-1", external_id="EXT-1",
        fields={"status": {"name": "Done"}})

    assert first.status == "applied"
    assert second.id == first.id
    assert await sync_events.count({"integrationId": integration.id}) == 1
    refreshed = await backlog_items.require(story.id)
    assert refreshed.execution_status == ExecutionStatus.IN_PROGRESS


async def test_echo_of_our_own_publication_does_not_loop(project, lead_user):
    epic, story, event = await _approved_epic(project, lead_user)
    integration = await _configured(project, lead_user)
    await external_mappings.insert(ExternalMapping(
        project_id=project.id, integration_id=integration.id, internal_id=story.id,
        internal_type="story", external_id="EXT-2"))

    result = await service.ingest_remote_change(
        project.id, integration.id, event_id="evt-echo", external_id="EXT-2",
        fields={"summary": "Changed remotely"}, origin=service.ORIGIN_MARKER)
    assert result.status == "ignored"
    assert "Echo" in result.error


async def test_external_status_change_does_not_touch_artifact_approval(project,
                                                                       lead_user):
    """AT-10 — delivery state updates while the approved artifact stays approved."""
    epic, story, event = await _approved_epic(project, lead_user)
    integration = await _configured(project, lead_user)
    await external_mappings.insert(ExternalMapping(
        project_id=project.id, integration_id=integration.id, internal_id=story.id,
        internal_type="story", external_id="EXT-3",
        last_common_values={"executionStatus": "not_started"}))

    await service.ingest_remote_change(
        project.id, integration.id, event_id="evt-3", external_id="EXT-3",
        fields={"status": {"name": "Done"}})

    refreshed = await backlog_items.require(story.id)
    assert refreshed.execution_status == ExecutionStatus.DONE
    assert refreshed.approved_version == 1          # approval untouched
    assert refreshed.requires_reapproval is False
    from app.repositories import test_cases
    cases = await test_cases.list({"projectId": project.id, "storyId": story.id})
    assert all(c.review_state != "passed" for c in cases)


async def test_incoming_specification_change_creates_a_reviewable_change_request(
        project, lead_user):
    epic, story, event = await _approved_epic(project, lead_user)
    integration = await _configured(project, lead_user)
    await external_mappings.insert(ExternalMapping(
        project_id=project.id, integration_id=integration.id, internal_id=story.id,
        internal_type="story", external_id="EXT-4",
        last_common_values={"title": "Customer registers"}))

    await service.ingest_remote_change(
        project.id, integration.id, event_id="evt-4", external_id="EXT-4",
        fields={"summary": "Customer registers with a phone number"})

    requests = await change_requests.list({"projectId": project.id})
    assert requests and requests[0].origin == "connector"
    # The approved artifact is not silently rewritten.
    refreshed = await backlog_items.require(story.id)
    assert refreshed.title == "Customer registers"
    assert refreshed.approved_version == 1


async def test_concurrent_estimate_change_surfaces_a_three_way_conflict(project,
                                                                        lead_user):
    """AT-09 — both sides moved, so the field is a conflict, not a silent write."""
    from app.models.backlog import EstimateCreate, RoleEffort
    from app.services.estimation import save_estimate

    epic, story, event = await _approved_epic(project, lead_user)
    integration = await _configured(project, lead_user)
    await external_mappings.insert(ExternalMapping(
        project_id=project.id, integration_id=integration.id, internal_id=story.id,
        internal_type="story", external_id="EXT-5",
        last_common_values={"storyPoints": 5}))

    await save_estimate(project.id, story.id, EstimateCreate(
        story_points=8, role_efforts=[RoleEffort(role="engineering", hours=8)]),
        actor_id=lead_user.id)

    result = await service.ingest_remote_change(
        project.id, integration.id, event_id="evt-5", external_id="EXT-5",
        fields={"Microsoft.VSTS.Scheduling.StoryPoints": 13})

    assert result.status == "conflict"
    conflict = next(c for c in result.conflicts if c.field == "storyPoints")
    assert conflict.internal_value == 8
    assert conflict.external_value == 13
    assert conflict.common_value == 5


async def test_deletions_do_not_hard_delete_by_default(project, lead_user):
    integration = await _configured(project, lead_user)
    assert integration.allow_deletes is False
