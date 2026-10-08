"""System acceptance scenarios AT-01 to AT-20 (specification section 21).

One test per numbered scenario, driven through the API wherever the scenario is
observable there. This is the suite to run when the question is "does the system
do what was agreed", rather than "is this unit correct".
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date, timedelta

import pytest

from app.core.utils import utcnow
from tests.support import (BRIEF_EN, NOTES_EL, SCHEDULE_CSV, approve_subtree,
                                run_analysis, upload)

pytestmark = pytest.mark.acceptance

GREEK_TRANSCRIPT = """[00:12] Πελάτης: ο κατάλογος τιμολογίων πρέπει να φορτώνει γρήγορα.
[00:48] Αναλυτής: ποιος εγκρίνει την απενεργοποίηση ενός λογαριασμού;
[01:15] Πελάτης: δεν είναι σαφές ακόμη, θα το επιβεβαιώσουμε. TBD.
"""


async def _tree(lead, project_id, *, features=2, stories=(3, 2), with_tests=True):
    epic = await lead.post(f"/projects/{project_id}/backlog/items",
                           json={"type": "epic", "title": "Customer accounts",
                                 "acceptanceCriteria": ["The account outcome is validated"]})
    epic_id = epic.json()["item"]["id"]
    created = {"epic": epic_id, "features": [], "stories": []}
    for index in range(features):
        feature = await lead.post(f"/projects/{project_id}/backlog/items",
                                  json={"type": "feature", "title": f"Feature {index + 1}",
                                        "parentId": epic_id,
                                        "acceptanceCriteria": ["The outcome is demonstrated"]})
        feature_id = feature.json()["item"]["id"]
        created["features"].append(feature_id)
        for number in range(stories[index]):
            story = await lead.post(
                f"/projects/{project_id}/backlog/items",
                json={"type": "story", "title": f"Story {index + 1}.{number + 1}",
                      "parentId": feature_id,
                      "acceptanceCriteria": ["A registered customer can sign in"]})
            story_id = story.json()["item"]["id"]
            created["stories"].append(story_id)
            if with_tests:
                await lead.post(f"/projects/{project_id}/tests",
                                json={"title": f"Verify {story_id[:6]}",
                                      "storyId": story_id})
    return created


# --- AT-01 ------------------------------------------------------------------

async def test_at01_mixed_language_evidence_is_associated_and_navigable(lead, project):
    """Greek recording transcript, English brief and a spreadsheet schedule."""
    brief = await upload(lead, project["id"], "brief.md", BRIEF_EN,
                         kind="brief", authority="contractual")
    notes = await upload(lead, project["id"], "notes-el.md", NOTES_EL,
                         kind="meeting_notes")
    schedule = await upload(lead, project["id"], "schedule.csv", SCHEDULE_CSV,
                            kind="schedule")
    recording = await upload(lead, project["id"], "kickoff.md", "# Kick off\n\nplaceholder",
                             kind="meeting_notes")
    await lead.post(
        f"/projects/{project['id']}/sources/versions/{recording['currentVersionId']}/transcript",
        json={"text": GREEK_TRANSCRIPT})

    listing = await lead.get(f"/projects/{project['id']}/sources")
    assert {row["id"] for row in listing.json()} == {
        brief["id"], notes["id"], schedule["id"], recording["id"]}
    assert all(row["currentVersion"] == 1 for row in listing.json())

    # Locators are navigable: paragraph, cell range and timestamp.
    kinds = set()
    for source in (brief, notes, schedule, recording):
        content = await lead.get(
            f"/projects/{project['id']}/sources/{source['id']}/content")
        kinds |= {chunk["locatorKind"] for chunk in content.json()["chunks"]}
    assert {"paragraph", "row", "timestamp"} <= kinds

    # Uncertainty stays visible: the unresolved point is recoverable from the text.
    segments = await lead.get(
        f"/projects/{project['id']}/sources/{recording['id']}/transcript")
    assert any("TBD" in segment["text"] for segment in segments.json())
    assert all(segment["speakerVerified"] is False for segment in segments.json())


# --- AT-02 ------------------------------------------------------------------

async def test_at02_unsupported_assumption_is_labelled_not_confirmed(lead,
                                                                     project_with_evidence):
    """The technical analyst labels assumptions; QA judges testability."""
    await run_analysis(lead, project_with_evidence["id"])

    requirements = await lead.get(f"/projects/{project_with_evidence['id']}/requirements")
    rows = requirements.json()
    assert rows
    # Nothing generated may masquerade as a confirmed client decision.
    assert not any(row["provenance"] == "client_decision" for row in rows)
    assert any(row["provenance"] == "ai_suggestion" for row in rows)

    nfrs = [row for row in rows if row["type"] == "non_functional"]
    assert nfrs, "the technical analyst proposes measurable targets"
    assert all(row["provenance"] == "ai_suggestion" for row in nfrs)

    specifications = await lead.get(
        f"/projects/{project_with_evidence['id']}/specifications")
    api_spec = next((s for s in specifications.json() if s["kind"] == "api"), None)
    if api_spec:
        assert "not an implemented contract" in api_spec["validation"]["note"]


# --- AT-03 ------------------------------------------------------------------

async def test_at03_one_approval_covers_the_exact_descendant_manifest(lead, project):
    """Epic with two features, five stories and linked tests."""
    ids = await _tree(lead, project["id"])

    preview = await lead.post(f"/projects/{project['id']}/approvals/preview/{ids['epic']}")
    manifest = preview.json()
    assert manifest["counts"] == {"epic": 1, "feature": 2, "story": 5, "test_case": 5}

    event = (await approve_subtree(lead, project["id"], ids["epic"])).json()
    assert event["committed"] is True
    assert len([e for e in event["entries"] if not e["inherited"]]) == 1
    assert len([e for e in event["entries"] if e["inherited"]]) == 12

    # Every inherited approval references the parent decision.
    for story_id in ids["stories"]:
        detail = await lead.get(f"/projects/{project['id']}/backlog/items/{story_id}")
        assert detail.json()["item"]["approvedVersion"] == 1
        current = detail.json()["version"]
        assert current["inheritedFromEventId"] == event["id"]
        assert current["approvalEventId"] == event["id"]


# --- AT-04 ------------------------------------------------------------------

async def test_at04_change_during_submission_fails_atomically(lead, project):
    ids = await _tree(lead, project["id"])
    preview = await lead.post(f"/projects/{project['id']}/approvals/preview/{ids['epic']}")
    manifest = preview.json()

    await lead.patch(f"/projects/{project['id']}/backlog/items/{ids['stories'][0]}",
                     json={"description": "Changed mid flight"})

    response = await lead.post(f"/projects/{project['id']}/approvals/decisions",
                               json={"manifestId": manifest["id"],
                                     "manifestHash": manifest["manifestHash"],
                                     "decision": "approve", "waivers": []})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "version_conflict"
    assert response.json()["error"]["details"]["refreshedHash"]

    # No partial approval anywhere in the subtree.
    tree = await lead.get(f"/projects/{project['id']}/backlog/tree")

    def walk(nodes):
        for node in nodes:
            assert node["approvedVersion"] is None
            walk(node["children"])

    walk(tree.json())
    assert (await lead.get(f"/projects/{project['id']}/approvals/events")).json() == []


# --- AT-05 ------------------------------------------------------------------

async def test_at05_a_new_story_is_not_covered_by_an_earlier_approval(lead, project):
    ids = await _tree(lead, project["id"])
    await approve_subtree(lead, project["id"], ids["epic"])

    added = await lead.post(f"/projects/{project['id']}/backlog/items",
                            json={"type": "story", "title": "Added after approval",
                                  "parentId": ids["features"][0],
                                  "acceptanceCriteria": ["A new observable outcome"]})
    new_id = added.json()["item"]["id"]

    detail = await lead.get(f"/projects/{project['id']}/backlog/items/{new_id}")
    assert detail.json()["item"]["approvedVersion"] is None
    assert detail.json()["item"]["state"] == "draft"

    epic = await lead.get(f"/projects/{project['id']}/backlog/items/{ids['epic']}")
    assert epic.json()["item"]["requiresReapproval"] is True


# --- AT-06 ------------------------------------------------------------------

async def test_at06_unreachable_local_model_pauses_without_cloud_fallback(
        lead, project_with_evidence, monkeypatch):
    """A local only job fails or pauses visibly; no content is sent anywhere."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "local_inference_url", "http://127.0.0.1:9/dead")
    job = await run_analysis(lead, project_with_evidence["id"])

    assert job["status"] == "paused"
    assert "could not run" in job["message"]
    assert job["stages"][0]["status"] == "failed"
    error = job["stages"][0]["error"]
    assert "is not available" in error
    assert "no project content was sent anywhere else" in error

    egress = await lead.get(f"/projects/{project_with_evidence['id']}/egress")
    assert egress.json() == [], "nothing may be sent outward on a local only project"


# --- AT-07 ------------------------------------------------------------------

async def test_at07_restricted_excerpt_is_blocked_and_recorded(lead, project):
    """The egress gate refuses and writes a policy event."""
    from app.ai import egress
    from app.core.config import settings
    from app.models.common import Classification
    from app.repositories import projects as projects_repo

    await lead.patch(f"/projects/{project['id']}",
                     json={"aiPolicy": {"localOnly": False, "cloudEnabled": True,
                                        "maxCloudClassification": "confidential",
                                        "sanitizePayloads": True,
                                        "localTranscription": True, "localOcr": True,
                                        "localEmbeddings": True}})
    stored = await projects_repo.require(project["id"])

    settings.cloud_enabled_globally = True
    try:
        with pytest.raises(egress.EgressDenied):
            await egress.prepare(stored, target="cloud", role="business_analyst",
                                 model_id="cloud/test",
                                 chunks=[(str(Classification.RESTRICTED),
                                          "the confidential rate card")],
                                 categories=["evidence_excerpt"])
    finally:
        settings.cloud_enabled_globally = False

    log = await lead.get(f"/projects/{project['id']}/egress")
    entry = log.json()[0]
    assert entry["allowed"] is False
    assert "restricted" in entry["blockedReason"]
    assert entry["charCount"] == 0
    assert "rate card" not in json.dumps(entry), "the payload is never stored"


# --- AT-08 ------------------------------------------------------------------

async def test_at08_replayed_publication_and_webhook_create_no_duplicates(lead, project):
    from app.models.integration import ExternalMapping
    from app.repositories import external_mappings, outbox, sync_events
    from app.services import integrations as service

    ids = await _tree(lead, project["id"], features=1, stories=(1,))
    event = (await approve_subtree(lead, project["id"], ids["epic"])).json()

    integration = await lead.post(f"/projects/{project['id']}/integrations",
                                  json={"provider": "jira", "name": "Jira",
                                        "externalProjectKey": "PORTAL"})
    integration_id = integration.json()["id"]
    await lead.post(f"/projects/{project['id']}/integrations/{integration_id}/discover")
    await lead.patch(f"/projects/{project['id']}/integrations/{integration_id}",
                     json={"enabled": True, "isPrimary": True})
    await lead.post(
        f"/projects/{project['id']}/integrations/{integration_id}/approve-mapping")

    first = await lead.post(
        f"/projects/{project['id']}/integrations/{integration_id}/publish",
        json={"approvalEventId": event["id"], "idempotencyKey": "publish-1"})
    second = await lead.post(
        f"/projects/{project['id']}/integrations/{integration_id}/publish",
        json={"approvalEventId": event["id"], "idempotencyKey": "publish-1"})
    assert first.json()["id"] == second.json()["id"]
    assert await outbox.count({"projectId": project["id"]}) == 1

    await external_mappings.insert(ExternalMapping(
        project_id=project["id"], integration_id=integration_id,
        internal_id=ids["stories"][0], internal_type="story", external_id="EXT-1",
        last_common_values={"executionStatus": "not_started"}))
    applied = await service.ingest_remote_change(
        project["id"], integration_id, event_id="evt-1", external_id="EXT-1",
        fields={"status": {"name": "In Progress"}})
    replayed = await service.ingest_remote_change(
        project["id"], integration_id, event_id="evt-1", external_id="EXT-1",
        fields={"status": {"name": "Done"}})
    assert applied.id == replayed.id
    assert await sync_events.count({"integrationId": integration_id}) == 1

    story = await lead.get(f"/projects/{project['id']}/backlog/items/{ids['stories'][0]}")
    assert story.json()["item"]["executionStatus"] == "in_progress"


# --- AT-09 ------------------------------------------------------------------

async def test_at09_concurrent_estimate_changes_surface_as_a_conflict(lead, project):
    from app.models.integration import ExternalMapping
    from app.repositories import external_mappings
    from app.services import integrations as service

    ids = await _tree(lead, project["id"], features=1, stories=(1,))
    story_id = ids["stories"][0]
    await lead.post(f"/projects/{project['id']}/backlog/items/{story_id}/estimate",
                    json={"method": "expert", "storyPoints": 5,
                          "roleEfforts": [{"role": "engineering", "hours": 8}]})
    baseline = await lead.post(f"/projects/{project['id']}/baselines",
                               json={"name": "Agreed plan"})

    integration = await lead.post(f"/projects/{project['id']}/integrations",
                                  json={"provider": "azure_devops", "name": "Boards"})
    integration_id = integration.json()["id"]
    await external_mappings.insert(ExternalMapping(
        project_id=project["id"], integration_id=integration_id, internal_id=story_id,
        internal_type="story", external_id="EXT-9",
        last_common_values={"storyPoints": 5}))

    # Both sides move away from the last agreed value.
    await lead.post(f"/projects/{project['id']}/backlog/items/{story_id}/estimate",
                    json={"method": "expert", "storyPoints": 8,
                          "roleEfforts": [{"role": "engineering", "hours": 13}]})
    result = await service.ingest_remote_change(
        project["id"], integration_id, event_id="evt-9", external_id="EXT-9",
        fields={"Microsoft.VSTS.Scheduling.StoryPoints": 13})

    assert result.status == "conflict"
    conflict = next(c for c in result.conflicts if c.field == "storyPoints")
    assert (conflict.internal_value, conflict.external_value, conflict.common_value) \
        == (8, 13, 5)

    conflicts = await lead.get(
        f"/projects/{project['id']}/integrations/{integration_id}/conflicts")
    assert len(conflicts.json()) == 1

    # The approved baseline is untouched by the remote change.
    stored = await lead.get(f"/projects/{project['id']}/baselines")
    assert stored.json()[0]["totals"]["storyPoints"] == baseline.json()["totals"]["storyPoints"]


# --- AT-10 ------------------------------------------------------------------

async def test_at10_external_status_does_not_change_approval_or_test_state(lead, project):
    from app.models.integration import ExternalMapping
    from app.repositories import external_mappings
    from app.services import integrations as service

    ids = await _tree(lead, project["id"], features=1, stories=(1,))
    story_id = ids["stories"][0]
    await approve_subtree(lead, project["id"], ids["epic"])

    integration = await lead.post(f"/projects/{project['id']}/integrations",
                                  json={"provider": "jira", "name": "Jira"})
    await external_mappings.insert(ExternalMapping(
        project_id=project["id"], integration_id=integration.json()["id"],
        internal_id=story_id, internal_type="story", external_id="EXT-10",
        last_common_values={"executionStatus": "not_started"}))

    await service.ingest_remote_change(
        project["id"], integration.json()["id"], event_id="evt-10",
        external_id="EXT-10", fields={"status": {"name": "Done"}})

    detail = await lead.get(f"/projects/{project['id']}/backlog/items/{story_id}")
    assert detail.json()["item"]["executionStatus"] == "done"
    assert detail.json()["item"]["approvedVersion"] == 1
    assert detail.json()["item"]["requiresReapproval"] is False
    assert all(test["reviewState"] != "passed" for test in detail.json()["tests"])


# --- AT-11 ------------------------------------------------------------------

async def test_at11_client_is_denied_cost_reports_and_unrelated_sources(lead, project,
                                                                        reviewer):
    ids = await _tree(lead, project["id"], features=1, stories=(1,))
    await upload(lead, project["id"], "internal.md",
                 "# Internal\n\nThe margin must stay internal.")
    await approve_subtree(lead, project["id"], ids["epic"])
    await lead.post(f"/projects/{project['id']}/members",
                    json={"email": reviewer.user.email, "roles": ["client_reviewer"]})
    await lead.post(f"/projects/{project['id']}/shares",
                    json={"audienceEmail": reviewer.user.email,
                          "itemIds": [ids["stories"][0]]})

    for url in [f"/projects/{project['id']}/cost-summary",
                f"/projects/{project['id']}/charts/cost",
                f"/projects/{project['id']}/sources",
                f"/projects/{project['id']}/rate-cards"]:
        response = await reviewer.get(url)
        assert response.status_code == 403, url
        assert "margin" not in response.text

    report = await reviewer.post(f"/projects/{project['id']}/reports/preview",
                                 json={"dataset": "cost_forecast"})
    assert report.status_code == 403

    workspace = await reviewer.get(f"/client/projects/{project['id']}/workspace")
    assert len(workspace.json()["items"]) == 1
    assert "margin" not in workspace.text


# --- AT-12 ------------------------------------------------------------------

async def test_at12_parent_rough_estimate_is_a_comparison_value(lead, project):
    ids = await _tree(lead, project["id"], features=1, stories=(3,), with_tests=False)
    for story_id, hours in zip(ids["stories"], (30, 30, 20)):
        await lead.post(f"/projects/{project['id']}/backlog/items/{story_id}/estimate",
                        json={"method": "expert",
                              "roleEfforts": [{"role": "engineering", "hours": hours}]})

    await lead.post(f"/projects/{project['id']}/backlog/items/{ids['epic']}/estimate",
                    json={"method": "analogy", "likelyHours": 100, "isRoughParent": True,
                          "roleEfforts": [{"role": "engineering", "hours": 100}]})
    await lead.post(f"/projects/{project['id']}/backlog/items/{ids['epic']}/estimate",
                    json={"method": "expert", "overheadHours": 12, "roleEfforts": []})

    rollup = (await lead.get(
        f"/projects/{project['id']}/backlog/items/{ids['epic']}/rollup")).json()
    assert rollup["childrenHours"] == 80.0
    assert rollup["ownOverheadHours"] == 12.0
    assert rollup["detailedHours"] == 92.0
    assert rollup["roughParentHours"] == 100.0
    assert any("kept for comparison" in warning for warning in rollup["warnings"])


# --- AT-13 ------------------------------------------------------------------

async def test_at13_excel_and_json_exports_agree(lead, project):
    ids = await _tree(lead, project["id"], features=1, stories=(2,))
    await lead.post(f"/projects/{project['id']}/backlog/items/{ids['stories'][0]}/estimate",
                    json={"method": "expert", "storyPoints": 5,
                          "roleEfforts": [{"role": "engineering", "hours": 8}]})
    await lead.patch(f"/projects/{project['id']}/backlog/items/{ids['stories'][1]}",
                     json={"title": "Ελληνικός τίτλος με τόνους"})

    preview = (await lead.post(f"/projects/{project['id']}/reports/preview",
                               json={"dataset": "backlog"})).json()
    xlsx = (await lead.post(f"/projects/{project['id']}/exports",
                            json={"dataset": "backlog", "format": "xlsx"})).json()
    as_json = (await lead.post(f"/projects/{project['id']}/exports",
                               json={"dataset": "backlog", "format": "json"})).json()

    assert xlsx["rowCounts"]["backlog"] == preview["totalRows"]
    payload = json.loads((await lead.get(
        f"/projects/{project['id']}/exports/{as_json['exportJobId']}/download")).content)
    assert payload["rowCounts"]["backlog"] == preview["totalRows"]
    assert payload["units"] == {"effort": "person_hours", "hoursPerPersonDay": 8.0}
    assert payload["currency"] == "EUR"
    assert payload["timezone"]

    stable_ids = {row["stableId"] for row in payload["entities"]["backlog"]}
    assert stable_ids == {row["stableId"] for row in preview["rows"]}
    assert any("Ελληνικός" in row["title"] for row in payload["entities"]["backlog"])

    workbook = (await lead.get(
        f"/projects/{project['id']}/exports/{xlsx['exportJobId']}/download")).content
    with zipfile.ZipFile(io.BytesIO(workbook)) as archive:
        shared = archive.read("xl/sharedStrings.xml").decode("utf-8")
    assert "Ελληνικός" in shared, "Unicode survives the spreadsheet round trip"


# --- AT-14 ------------------------------------------------------------------

async def test_at14_legacy_xls_splits_instead_of_truncating():
    from app.core.utils import utcnow as now
    from app.models.collaboration import ReportPreview
    from app.services import exports

    rows = exports.XLS_MAX_ROWS + 10
    preview = ReportPreview(
        dataset="backlog",
        columns=[{"key": "a", "label": "A", "type": "string"},
                 {"key": "b", "label": "B", "type": "string"}],
        rows=[{"a": f"row-{index}", "b": "x"} for index in range(rows)],
        total_rows=rows, snapshot_id="snap-test", generated_at=now())

    data, warnings, counts = exports.build_xls({"backlog": preview}, title="Overflow")
    assert data[:4] == b"\xd0\xcf\x11\xe0"
    assert any("exceeds the .xls limit" in warning for warning in warnings)
    assert sum(counts.values()) == rows, "no row is silently dropped"
    assert max(counts.values()) <= exports.XLS_MAX_ROWS - 1


# --- AT-15 ------------------------------------------------------------------

async def test_at15_source_revision_produces_an_impact_report(lead, project_with_evidence):
    await run_analysis(lead, project_with_evidence["id"])
    sources = await lead.get(f"/projects/{project_with_evidence['id']}/sources")
    brief = next(row for row in sources.json() if row["title"] == "brief.md")

    revised = BRIEF_EN.replace("under 2 seconds", "under 5 seconds")
    await upload(lead, project_with_evidence["id"], "brief.md", revised,
                 document_id=brief["id"])

    impact = await lead.get(f"/projects/{project_with_evidence['id']}/sources/impact")
    assert impact.status_code == 200
    report = impact.json()[0]
    assert report["summary"]["total"] >= 1
    assert report["affected"]

    tree = await lead.get(f"/projects/{project_with_evidence['id']}/backlog/tree")

    def any_stale(nodes):
        return any(node["stale"] or any_stale(node["children"]) for node in nodes)

    assert any_stale(tree.json()), "linked items are marked potentially stale"


# --- AT-16 ------------------------------------------------------------------

async def test_at16_without_history_templates_are_used_and_no_accuracy_is_claimed(
        lead, admin, project_with_evidence):
    await run_analysis(lead, project_with_evidence["id"])

    tree = await lead.get(f"/projects/{project_with_evidence['id']}/backlog/tree")

    def first_story(nodes):
        for node in nodes:
            if node["type"] == "story":
                return node
            found = first_story(node["children"])
            if found:
                return found
        return None

    story = first_story(tree.json())
    assert story is not None
    detail = await lead.get(
        f"/projects/{project_with_evidence['id']}/backlog/items/{story['id']}")
    estimate = detail.json()["estimate"]
    assert estimate["method"] == "ai_proposed"
    assert estimate["confidenceLabel"] == "indicative"
    assert any("not a commitment" in assumption.lower()
               for assumption in estimate["assumptions"])

    candidate = await admin.post("/admin/calibration/candidates", json={})
    assert candidate.json()["sufficient"] is False
    assert "insufficientEvidence" in candidate.json()["evaluation"]


# --- AT-17 ------------------------------------------------------------------

async def test_at17_a_candidate_that_does_not_improve_stays_inactive(admin, lead,
                                                                     project):
    """A cohort where the current method is already unbiased must not activate."""
    from app.models.backlog import BacklogItem, Estimate, RoleEffort
    from app.models.common import ExecutionStatus, ItemType
    from app.models.planning import StatusEvent, Worklog
    from app.repositories import backlog_items, estimates, status_events, worklogs

    start = date(2026, 1, 1)
    for index in range(32):
        item = BacklogItem(project_id=project["id"], stable_id=f"STORY-{index:03d}",
                           type=ItemType.STORY, title=f"Historic story {index}",
                           execution_status=ExecutionStatus.DONE)
        await backlog_items.insert(item)
        await estimates.insert(Estimate(
            project_id=project["id"], item_id=item.id, method="expert",
            role_efforts=[RoleEffort(role="engineering", hours=10.0)]))
        await worklogs.insert(Worklog(
            project_id=project["id"], item_id=item.id, user_id="historic",
            role="engineering", work_date=start + timedelta(days=index),
            hours=10.0, approved=True))
        await status_events.insert(StatusEvent(
            project_id=project["id"], item_id=item.id, to_status="done",
            at=utcnow() - timedelta(days=60 - index)))

    candidate = await admin.post("/admin/calibration/candidates", json={})
    version = candidate.json()
    assert version["sufficient"] is True
    assert version["usableSize"] >= 30
    assert version["evaluation"]["improvesOnBaseline"] is False

    refused = await admin.post(f"/admin/calibration/{version['id']}/activate")
    assert refused.status_code == 409
    assert "did not improve" in refused.json()["error"]["message"]

    listed = await admin.get("/admin/calibration")
    assert all(row["status"] != "active" for row in listed.json())


# --- AT-18 ------------------------------------------------------------------

async def test_at18_a_restored_dataset_keeps_its_links_and_rebuildable_index(
        lead, project_with_evidence, in_memory_db):
    """Source, version and approval links stay coherent; the index is derived."""
    from app.db.mongo import C
    from app.repositories import source_chunks
    from app.services import search

    await run_analysis(lead, project_with_evidence["id"])
    ids = await _tree(lead, project_with_evidence["id"], features=1, stories=(1,))
    event = (await approve_subtree(lead, project_with_evidence["id"], ids["epic"])).json()

    # Simulate a dump and restore of the authoritative collections.
    dump: dict[str, list[dict]] = {}
    for name in [C.PROJECTS, C.BACKLOG_ITEMS, C.ARTIFACT_VERSIONS, C.APPROVAL_EVENTS,
                 C.SOURCE_DOCUMENTS, C.SOURCE_VERSIONS, C.EVIDENCE_LINKS, C.TEST_CASES]:
        dump[name] = await in_memory_db[name].find({}).to_list(length=None)
    # The retrieval index is derived data and is dropped, as it would be on restore.
    await source_chunks.delete_many({})
    for name, documents in dump.items():
        await in_memory_db[name].delete_many({})
        if documents:
            await in_memory_db[name].insert_many(documents)

    restored_event = await lead.get(
        f"/projects/{project_with_evidence['id']}/approvals/events")
    assert restored_event.json()[0]["id"] == event["id"]

    for entry in event["entries"]:
        if entry["itemType"] in {"epic", "feature", "story"}:
            detail = await lead.get(
                f"/projects/{project_with_evidence['id']}/backlog/items/{entry['itemId']}")
            assert detail.status_code == 200
            assert detail.json()["item"]["approvedVersion"] == entry["version"]

    trace = await lead.get(f"/projects/{project_with_evidence['id']}/traceability")
    assert trace.json()["edges"], "evidence links survive the restore"

    # Rebuilding the index from the authoritative sources restores retrieval.
    assert await search.search(project_with_evidence["id"], "invoice",
                               allowed_classifications={"confidential"}) == []
    from app.services import sources as source_service
    from app.repositories import source_versions
    from app.services import extraction

    for version in await source_versions.list({"projectId": project_with_evidence["id"]}):
        if not version.normalized_text:
            continue
        document = (await lead.get(
            f"/projects/{project_with_evidence['id']}/sources")).json()
        result = extraction.extract(version.normalized_text.encode("utf-8"),
                                    version.filename, "brief")
        await source_service._store_chunks(
            project_with_evidence["id"],
            await source_service.source_documents.require(version.document_id),
            version, result, "confidential")
    rebuilt = await search.search(project_with_evidence["id"], "invoice",
                                  allowed_classifications={"confidential"})
    assert rebuilt, "the index is rebuildable from the authoritative sources"


# --- AT-19 ------------------------------------------------------------------

async def test_at19_invalid_gherkin_blocks_the_artifact(lead, project):
    missing_value = """Feature: Limits
  Scenario Outline: Boundary
    Given a configured limit
    When the value <value> is submitted
    Then the outcome is <outcome>

    Examples:
      | value | outcome |
      |       | rejected |
"""
    invalid_syntax = "Scenario: no feature keyword at all\n  Given something"

    for document in (missing_value, invalid_syntax):
        validation = await lead.post(f"/projects/{project['id']}/tests/validate-gherkin",
                                     json={"text": document})
        assert validation.json()["valid"] is False
        assert validation.json()["errors"]

        refused = await lead.post(f"/projects/{project['id']}/tests",
                                  json={"title": "Blocked", "gherkinText": document})
        assert refused.status_code == 422


# --- AT-20 ------------------------------------------------------------------

async def test_at20_a_static_screenshot_raises_questions_rather_than_inventing(lead,
                                                                              project):
    response = await lead.post(
        f"/projects/{project['id']}/sources",
        files={"file": ("checkout.png", b"\x89PNG\r\n\x1a\n", "image/png")},
        data={"meta": json.dumps({"title": "Checkout screen", "kind": "image"})})
    assert response.status_code == 201
    source = response.json()

    assert source["status"] == "unsupported"
    assert source["chunkCount"] == 0, "no UI behaviour is invented from a bitmap"
    codes = {warning["code"] for warning in source["warnings"]}
    assert "ocr_required" in codes
    message = next(w["message"] for w in source["warnings"] if w["code"] == "ocr_required")
    assert "interaction and business behaviour must be asked about" in message

    versions = await lead.get(f"/projects/{project['id']}/sources/{source['id']}/versions")
    assert "OCR" in versions.json()[0]["failureReason"]
