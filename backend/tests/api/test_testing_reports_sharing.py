"""Testbook, report builder, export, sharing and administration functionality
(sections 13, 15, 16 and the administration screen)."""
from __future__ import annotations

import io
import json
import zipfile

from tests.support import approve_subtree

VALID_GHERKIN = """@STORY-001 @AC-001-01 @positive
Feature: Registration
  Scenario: A customer registers with a valid email address
    Given an unregistered visitor
    When they submit a valid email address
    Then a verification email is sent
"""

INVALID_GHERKIN = """Feature: Broken
  Scenario Outline: Missing value
    Given a limit
    When the value <value> is submitted
    Then the outcome is <outcome>

    Examples:
      | value | outcome |
      |       | rejected |
"""


async def _approved_story(lead, project_id: str) -> dict[str, str]:
    epic = await lead.post(f"/projects/{project_id}/backlog/items",
                           json={"type": "epic", "title": "Accounts",
                                 "acceptanceCriteria": ["Outcome validated"]})
    epic_id = epic.json()["item"]["id"]
    feature = await lead.post(f"/projects/{project_id}/backlog/items",
                              json={"type": "feature", "title": "Registration",
                                    "parentId": epic_id,
                                    "acceptanceCriteria": ["Outcome demonstrated"]})
    story = await lead.post(f"/projects/{project_id}/backlog/items",
                            json={"type": "story", "title": "Customer registers",
                                  "parentId": feature.json()["item"]["id"],
                                  "acceptanceCriteria": ["A customer can register"]})
    story_id = story.json()["item"]["id"]
    await lead.post(f"/projects/{project_id}/tests",
                    json={"title": "Registration works", "storyId": story_id})
    await lead.post(f"/projects/{project_id}/backlog/items/{story_id}/estimate",
                    json={"method": "expert", "storyPoints": 5,
                          "roleEfforts": [{"role": "engineering", "hours": 8}]})
    await approve_subtree(lead, project_id, epic_id)
    return {"epic": epic_id, "story": story_id}


# --- testbook ---------------------------------------------------------------

async def test_gherkin_validation_accepts_valid_and_rejects_invalid(lead, project):
    valid = await lead.post(f"/projects/{project['id']}/tests/validate-gherkin",
                            json={"text": VALID_GHERKIN})
    assert valid.status_code == 200
    assert valid.json()["valid"] is True
    assert "@positive" in valid.json()["tags"]

    invalid = await lead.post(f"/projects/{project['id']}/tests/validate-gherkin",
                              json={"text": INVALID_GHERKIN})
    assert invalid.json()["valid"] is False
    assert any("empty value" in error["message"] for error in invalid.json()["errors"])


async def test_creating_a_test_with_invalid_gherkin_is_refused(lead, project):
    response = await lead.post(f"/projects/{project['id']}/tests",
                               json={"title": "Broken", "gherkinText": INVALID_GHERKIN})
    assert response.status_code == 422
    assert response.json()["error"]["details"]["errors"]


async def test_gherkin_renders_in_both_dialects_from_one_structure(lead, project):
    created = await lead.post(f"/projects/{project['id']}/tests",
                              json={"title": "Registration", "gherkinText": VALID_GHERKIN})
    assert created.status_code == 201
    test_id = created.json()["id"]

    english = await lead.get(f"/projects/{project['id']}/tests/{test_id}/gherkin",
                             params={"dialect": "en"})
    greek = await lead.get(f"/projects/{project['id']}/tests/{test_id}/gherkin",
                           params={"dialect": "el"})
    assert "Feature: Registration" in english.json()["text"]
    assert "Λειτουργία: Registration" in greek.json()["text"]
    assert "Δεδομένου" in greek.json()["text"]
    assert greek.json()["validation"]["valid"] is True


async def test_generated_tests_are_drafts_and_never_passed(lead, analysed_project):
    response = await lead.get(f"/projects/{analysed_project['id']}/tests")
    assert response.status_code == 200
    cases = response.json()
    assert cases
    assert all(case["reviewState"] == "pending_review" for case in cases)
    assert all(case["state"] == "draft" for case in cases)


async def test_coverage_matrix_flags_both_directions(lead, project):
    epic = await lead.post(f"/projects/{project['id']}/backlog/items",
                           json={"type": "epic", "title": "Accounts",
                                 "acceptanceCriteria": ["Outcome"]})
    feature = await lead.post(f"/projects/{project['id']}/backlog/items",
                              json={"type": "feature", "title": "Registration",
                                    "parentId": epic.json()["item"]["id"],
                                    "acceptanceCriteria": ["Outcome"]})
    await lead.post(f"/projects/{project['id']}/backlog/items",
                    json={"type": "story", "title": "Uncovered story",
                          "parentId": feature.json()["item"]["id"],
                          "acceptanceCriteria": ["An observable outcome"]})
    await lead.post(f"/projects/{project['id']}/tests",
                    json={"title": "Unlinked test"})

    response = await lead.get(f"/projects/{project['id']}/tests/coverage")
    assert response.status_code == 200
    matrix = response.json()
    assert matrix["uncoveredCriteria"] >= 1
    assert matrix["unlinkedTests"]
    assert matrix["coveredPercent"] < 100


async def test_testbook_assembly_is_versioned_and_lists_gaps(lead, analysed_project):
    first = await lead.post(f"/projects/{analysed_project['id']}/testbooks",
                            json={"name": "Release 1 testbook"})
    assert first.status_code == 201
    assert first.json()["version"] == 1
    assert "never records a run status" in first.json()["purpose"]

    second = await lead.post(f"/projects/{analysed_project['id']}/testbooks",
                             json={"name": "Release 1 testbook"})
    assert second.json()["version"] == 2

    features = await lead.get(
        f"/projects/{analysed_project['id']}/testbooks/{second.json()['id']}/features")
    assert features.status_code == 200
    assert "Feature:" in features.text


# --- reports and exports ----------------------------------------------------

async def test_dataset_catalogue_reflects_the_callers_permissions(lead, project,
                                                                  outsider):
    await lead.post(f"/projects/{project['id']}/members",
                    json={"email": outsider.user.email, "roles": ["internal_viewer"]})

    full = await lead.get(f"/projects/{project['id']}/reports/datasets")
    limited = await outsider.get(f"/projects/{project['id']}/reports/datasets")
    assert full.status_code == limited.status_code == 200

    backlog_full = next(d for d in full.json() if d["dataset"] == "backlog")
    backlog_limited = next(d for d in limited.json() if d["dataset"] == "backlog")
    assert "estimatedCost" in {c["key"] for c in backlog_full["allowedColumns"]}
    assert "estimatedCost" not in {c["key"] for c in backlog_limited["allowedColumns"]}


async def test_report_preview_totals_match_the_rows(lead, project):
    await _approved_story(lead, project["id"])
    response = await lead.post(f"/projects/{project['id']}/reports/preview",
                               json={"dataset": "backlog"})
    assert response.status_code == 200
    preview = response.json()
    detail = round(sum(row["effortHours"] for row in preview["rows"]), 2)
    assert preview["totals"]["effortHours"] == detail
    assert preview["snapshotId"].startswith("snap-")


async def test_unsupported_filter_is_refused(lead, project):
    response = await lead.post(f"/projects/{project['id']}/reports/preview",
                               json={"dataset": "backlog",
                                     "filters": {"$where": "function(){return true}"}})
    assert response.status_code == 422
    assert response.json()["error"]["details"]["unknown"] == ["$where"]


async def test_a_saved_template_cannot_widen_permissions(lead, project, outsider):
    """A lead analyst may manage report templates but may not read cost."""
    await lead.post(f"/projects/{project['id']}/members",
                    json={"email": outsider.user.email, "roles": ["lead_analyst"]})

    allowed = await outsider.post(f"/projects/{project['id']}/reports/definitions",
                                  json={"name": "Scope", "dataset": "backlog",
                                        "fields": ["stableId", "title"]})
    assert allowed.status_code == 201

    denied = await outsider.post(f"/projects/{project['id']}/reports/definitions",
                                 json={"name": "Costs", "dataset": "backlog",
                                       "fields": ["stableId", "estimatedCost"]})
    assert denied.status_code == 403
    assert denied.json()["error"]["details"]["denied"] == ["estimatedCost"]


async def test_report_preview_refuses_a_field_the_caller_may_not_read(lead, project,
                                                                      outsider):
    await lead.post(f"/projects/{project['id']}/members",
                    json={"email": outsider.user.email, "roles": ["lead_analyst"]})
    response = await outsider.post(f"/projects/{project['id']}/reports/preview",
                                   json={"dataset": "backlog",
                                         "fields": ["stableId", "estimatedCost"]})
    assert response.status_code == 403
    assert response.json()["error"]["details"]["denied"] == ["estimatedCost"]


async def test_export_formats_and_download(lead, project):
    await _approved_story(lead, project["id"])

    xlsx = await lead.post(f"/projects/{project['id']}/exports",
                           json={"dataset": "backlog", "format": "xlsx"})
    assert xlsx.status_code == 202
    assert xlsx.json()["status"] == "succeeded"
    assert xlsx.json()["rowCounts"]["backlog"] == 3

    download = await lead.get(
        f"/projects/{project['id']}/exports/{xlsx.json()['exportJobId']}/download")
    assert download.status_code == 200
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert "xl/workbook.xml" in archive.namelist()

    as_json = await lead.post(f"/projects/{project['id']}/exports",
                              json={"format": "json"})
    job_id = as_json.json()["exportJobId"]
    payload = json.loads(
        (await lead.get(f"/projects/{project['id']}/exports/{job_id}/download")).content)
    assert payload["schemaVersion"] == "1.0"
    assert payload["units"]["hoursPerPersonDay"] == 8.0
    assert payload["currency"] == "EUR"
    assert payload["rowCounts"]["backlog"] == len(payload["entities"]["backlog"])


async def test_markdown_and_gherkin_bundles_export(lead, analysed_project):
    markdown = await lead.post(f"/projects/{analysed_project['id']}/exports",
                               json={"format": "markdown"})
    assert markdown.status_code == 202
    content = (await lead.get(
        f"/projects/{analysed_project['id']}/exports/"
        f"{markdown.json()['exportJobId']}/download")).content
    assert b"# Test project" in content or b"specifications" in content

    bundle = await lead.post(f"/projects/{analysed_project['id']}/exports",
                             json={"format": "gherkin"})
    archive_bytes = (await lead.get(
        f"/projects/{analysed_project['id']}/exports/"
        f"{bundle.json()['exportJobId']}/download")).content
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert any(name.endswith(".feature") for name in archive.namelist())
    assert "no run status is implied" in manifest["note"]


async def test_asynchronous_export_returns_a_job(lead, project):
    response = await lead.post(f"/projects/{project['id']}/exports",
                               params={"async": "true"},
                               json={"dataset": "backlog", "format": "xlsx"})
    assert response.status_code == 202
    assert response.json()["async"] is True
    assert response.json()["status"] == "queued"


# --- sharing and the client workspace ---------------------------------------

async def test_sharing_defaults_to_approved_versions(lead, project, reviewer):
    ids = await _approved_story(lead, project["id"])
    draft = await lead.post(f"/projects/{project['id']}/backlog/items",
                            json={"type": "epic", "title": "Unapproved"})

    refused = await lead.post(f"/projects/{project['id']}/shares",
                              json={"audienceEmail": reviewer.user.email,
                                    "itemIds": [draft.json()["item"]["id"]]})
    assert refused.status_code == 422
    assert "no approved version" in refused.json()["error"]["message"]

    granted = await lead.post(f"/projects/{project['id']}/shares",
                              json={"audienceEmail": reviewer.user.email,
                                    "itemIds": [ids["story"]],
                                    "allowAcceptance": True})
    assert granted.status_code == 201
    assert granted.json()["versions"][0]["draft"] is False


async def test_client_sees_only_granted_versions_without_internal_fields(
        lead, project, reviewer):
    ids = await _approved_story(lead, project["id"])
    await lead.post(f"/projects/{project['id']}/shares",
                    json={"audienceEmail": reviewer.user.email,
                          "itemIds": [ids["story"]], "allowAcceptance": True})

    listing = await reviewer.get("/client/projects")
    assert listing.status_code == 200
    assert listing.json()[0]["projectId"] == project["id"]

    workspace = await reviewer.get(f"/client/projects/{project['id']}/workspace")
    assert workspace.status_code == 200
    payload = workspace.json()
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    for forbidden in ("estimatedCost", "rate", "internalNotes", "modelId", "aiPrompt"):
        assert forbidden not in item
    assert payload["allowAcceptance"] is True


async def test_client_acceptance_is_separate_from_internal_approval(lead, project,
                                                                    reviewer):
    ids = await _approved_story(lead, project["id"])
    await lead.post(f"/projects/{project['id']}/shares",
                    json={"audienceEmail": reviewer.user.email,
                          "itemIds": [ids["story"]], "allowAcceptance": True})

    accepted = await reviewer.post(f"/client/projects/{project['id']}/acceptance",
                                   json={"itemIds": [ids["story"]], "accepted": True,
                                         "note": "Agreed"})
    assert accepted.status_code == 200

    detail = await lead.get(f"/projects/{project['id']}/backlog/items/{ids['story']}")
    assert detail.json()["item"]["clientAccepted"] is True
    assert detail.json()["item"]["approvedVersion"] == 1


async def test_client_cannot_accept_an_unshared_item(lead, project, reviewer):
    ids = await _approved_story(lead, project["id"])
    other = await lead.post(f"/projects/{project['id']}/backlog/items",
                            json={"type": "epic", "title": "Not shared"})
    await lead.post(f"/projects/{project['id']}/shares",
                    json={"audienceEmail": reviewer.user.email,
                          "itemIds": [ids["story"]], "allowAcceptance": True})

    response = await reviewer.post(f"/client/projects/{project['id']}/acceptance",
                                   json={"itemIds": [other.json()["item"]["id"]]})
    assert response.status_code == 403


async def test_revoking_a_grant_blocks_future_access(lead, project, reviewer):
    ids = await _approved_story(lead, project["id"])
    grant = await lead.post(f"/projects/{project['id']}/shares",
                            json={"audienceEmail": reviewer.user.email,
                                  "itemIds": [ids["story"]]})
    assert (await reviewer.get(
        f"/client/projects/{project['id']}/workspace")).status_code == 200

    await lead.post(f"/projects/{project['id']}/shares/{grant.json()['id']}/revoke")
    assert (await reviewer.get(
        f"/client/projects/{project['id']}/workspace")).status_code == 403


async def test_comment_visibility_separates_internal_from_client(lead, project, reviewer):
    ids = await _approved_story(lead, project["id"])
    await lead.post(f"/projects/{project['id']}/members",
                    json={"email": reviewer.user.email, "roles": ["client_reviewer"]})
    await lead.post(f"/projects/{project['id']}/shares",
                    json={"audienceEmail": reviewer.user.email, "itemIds": [ids["story"]]})

    await lead.post(f"/projects/{project['id']}/comments",
                    json={"targetType": "backlog_item", "targetId": ids["story"],
                          "body": "Internal: check the margin", "visibility": "internal"})
    client_comment = await reviewer.post(
        f"/projects/{project['id']}/comments",
        json={"targetType": "backlog_item", "targetId": ids["story"],
              "body": "Looks good to us"})
    assert client_comment.status_code == 201
    assert client_comment.json()["visibility"] == "client"

    refused = await reviewer.post(
        f"/projects/{project['id']}/comments",
        json={"targetType": "backlog_item", "targetId": ids["story"],
              "body": "Sneaky", "visibility": "internal"})
    assert refused.status_code == 403

    visible = await reviewer.get(f"/projects/{project['id']}/comments",
                                 params={"target_id": ids["story"]})
    assert [c["body"] for c in visible.json()] == ["Looks good to us"]

    internal = await lead.get(f"/projects/{project['id']}/comments",
                              params={"target_id": ids["story"]})
    assert len(internal.json()) == 2


# --- administration ---------------------------------------------------------

async def test_model_health_and_policy_are_reported(admin, lead, project):
    models = await admin.get("/admin/models")
    assert models.status_code == 200
    deployments = {row["deployment"] for row in models.json()["adapters"]}
    assert "local" in deployments
    assert models.json()["configuration"]["cloudEnabledGlobally"] is False

    policy = await lead.get(f"/projects/{project['id']}/policy")
    assert policy.status_code == 200
    assert policy.json()["policy"]["localOnly"] is True
    assert any("zero data disclosure" in line or "not mean" in line
               for line in policy.json()["explanation"])


async def test_audit_trail_records_decisions(lead, project):
    await _approved_story(lead, project["id"])
    response = await lead.get(f"/projects/{project['id']}/audit")
    assert response.status_code == 200
    actions = {row["action"] for row in response.json()}
    assert "project.created" in actions
    assert "approval.decided" in actions

    decision = next(row for row in response.json() if row["action"] == "approval.decided")
    assert decision["detail"]["inherited"] >= 1
    assert decision["detail"]["manifestHash"]


async def test_egress_log_is_readable_and_records_local_runs(lead, analysed_project):
    response = await lead.get(f"/projects/{analysed_project['id']}/egress")
    assert response.status_code == 200
    # Local processing writes no outbound manifest; the endpoint still answers.
    assert isinstance(response.json(), list)


async def test_calibration_reports_insufficient_evidence_honestly(admin):
    response = await admin.post("/admin/calibration/candidates", json={})
    assert response.status_code == 200
    version = response.json()
    assert version["sufficient"] is False
    assert version["evaluation"]["insufficientEvidence"] is True
    assert "Template estimates remain in use" in version["evaluation"]["message"]

    activation = await admin.post(f"/admin/calibration/{version['id']}/activate")
    assert activation.status_code == 409


async def test_admin_endpoints_refuse_non_administrators(lead):
    for url in ["/admin/models", "/admin/jobs", "/admin/users", "/admin/calibration"]:
        assert (await lead.get(url)).status_code == 403
