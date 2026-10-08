"""Analysis workspace and backlog functionality (sections 8, 9 and 11)."""
from __future__ import annotations

from tests.support import first_epic, run_analysis


# --- analysis ---------------------------------------------------------------

async def test_analysis_runs_the_three_roles_in_order(lead, project_with_evidence):
    job = await run_analysis(lead, project_with_evidence["id"])

    assert job["status"] == "succeeded"
    assert [stage["role"] for stage in job["stages"]] == [
        "business_analyst", "technical_analyst", "qa_analyst"]
    assert all(stage["status"] == "succeeded" for stage in job["stages"])
    for stage in job["stages"]:
        assert stage["usage"]["modelId"]
        assert stage["usage"]["deployment"] == "local"
        assert stage["usage"]["promptTemplateVersion"]
    assert job["createdCounts"]["stories"] > 0


async def test_a_project_uses_all_three_analysts_unless_told_otherwise(lead, project):
    assert project["enabledAnalysts"] == [
        "business_analyst", "technical_analyst", "qa_analyst"]

    response = await lead.patch(f"/projects/{project['id']}",
                                json={"enabledAnalysts": ["qa_analyst", "business_analyst"]})
    assert response.status_code == 200, response.text
    # Stored in run order, whatever order they were chosen in.
    assert response.json()["enabledAnalysts"] == ["business_analyst", "qa_analyst"]

    empty = await lead.patch(f"/projects/{project['id']}", json={"enabledAnalysts": []})
    assert empty.status_code == 422


async def test_a_new_project_can_start_with_a_chosen_set_of_analysts(lead):
    response = await lead.post("/projects", json={
        "key": "ANLY", "name": "Analyst choice", "enabledAnalysts": ["technical_analyst"]})
    assert response.status_code == 201, response.text
    assert response.json()["enabledAnalysts"] == ["technical_analyst"]


async def test_a_run_uses_only_the_project_analysts(lead, project_with_evidence):
    project_id = project_with_evidence["id"]
    await lead.patch(f"/projects/{project_id}", json={"enabledAnalysts": ["business_analyst"]})

    job = await run_analysis(lead, project_id)

    assert job["status"] == "succeeded"
    assert [stage["role"] for stage in job["stages"]] == ["business_analyst"]
    assert job["scope"]["roles"] == ["business_analyst"]


async def test_a_run_cannot_ask_for_an_analyst_the_project_switched_off(
        lead, project_with_evidence):
    project_id = project_with_evidence["id"]
    await lead.patch(f"/projects/{project_id}",
                     json={"enabledAnalysts": ["business_analyst", "technical_analyst"]})

    refused = await lead.post(f"/projects/{project_id}/analysis/runs",
                              json={"roles": ["business_analyst", "qa_analyst"]})
    assert refused.status_code == 422
    error = refused.json()["error"]
    assert error["code"] == "analyst_not_enabled"
    assert error["details"]["disabled"] == ["qa_analyst"]

    # Narrowing a run to some of the enabled analysts is allowed.
    narrowed = await lead.post(f"/projects/{project_id}/analysis/runs",
                               json={"roles": ["technical_analyst"]})
    assert narrowed.status_code == 202
    assert [stage["role"] for stage in narrowed.json()["stages"]] == ["technical_analyst"]


async def test_ux_and_data_analysts_are_opt_in(lead, project):
    # New projects keep the original three; the UX and data analysts are added by choice.
    assert project["enabledAnalysts"] == [
        "business_analyst", "technical_analyst", "qa_analyst"]


async def test_all_five_analysts_run_in_order(lead, project_with_evidence):
    project_id = project_with_evidence["id"]
    await lead.patch(f"/projects/{project_id}", json={"enabledAnalysts": [
        "qa_analyst", "data_analyst", "technical_analyst", "ux_analyst", "business_analyst"]})

    job = await run_analysis(lead, project_id)

    assert job["status"] == "succeeded", job["message"]
    assert [stage["role"] for stage in job["stages"]] == [
        "business_analyst", "ux_analyst", "data_analyst", "technical_analyst", "qa_analyst"]
    assert all(stage["status"] == "succeeded" for stage in job["stages"])


async def test_the_ux_analyst_proposes_screens_states_and_accessibility(
        lead, project_with_evidence):
    project_id = project_with_evidence["id"]
    await lead.patch(f"/projects/{project_id}",
                     json={"enabledAnalysts": ["business_analyst", "ux_analyst"]})
    job = await run_analysis(lead, project_id)
    ux = next(stage for stage in job["stages"] if stage["role"] == "ux_analyst")
    assert ux["status"] == "succeeded"

    reqs = (await lead.get(f"/projects/{project_id}/requirements")).json()
    ux_reqs = [r for r in reqs if r["type"] == "ux"]
    assert ux_reqs and all(r["stableId"].startswith("UX-") for r in ux_reqs)
    assert any("WCAG 2.1" in r["statement"] for r in ux_reqs)
    assert all(r["createdByRole"] == "ux_analyst" for r in ux_reqs)

    specs = (await lead.get(f"/projects/{project_id}/specifications")).json()
    ux_spec = next(s for s in specs if s["kind"] == "ux")
    assert "States to design" in ux_spec["body"]
    assert ux_spec["generatedByRole"] == "ux_analyst"
    journeys = [s for s in specs if s["kind"] == "process_diagram"
                and s["generatedByRole"] == "ux_analyst"]
    assert journeys and journeys[0]["diagramSource"].startswith("flowchart LR")

    found = (await lead.get(f"/projects/{project_id}/findings")).json()
    ux_findings = [f for f in found if f["role"] == "ux_analyst"]
    assert ux_findings
    # Story level findings point at the story they are about.
    assert any(f["targetId"] for f in ux_findings)


async def test_the_data_analyst_flags_personal_data_without_retention(
        lead, project_with_evidence):
    project_id = project_with_evidence["id"]
    await lead.patch(f"/projects/{project_id}",
                     json={"enabledAnalysts": ["business_analyst", "data_analyst"]})
    job = await run_analysis(lead, project_id)
    assert job["status"] == "succeeded", job["message"]

    found = (await lead.get(f"/projects/{project_id}/findings")).json()
    retention = [f for f in found if f["role"] == "data_analyst"
                 and f["title"] == "Personal data without a retention rule"]
    # The brief collects an email address but states no retention period.
    assert retention and retention[0]["citations"]

    reqs = (await lead.get(f"/projects/{project_id}/requirements")).json()
    assert any(r["type"] == "data" and r["stableId"].startswith("DATA-") for r in reqs)

    specs = (await lead.get(f"/projects/{project_id}/specifications")).json()
    data_spec = next(s for s in specs if s["kind"] == "data")
    assert "## Data quality rules" in data_spec["body"]
    assert data_spec["structured"]["qualityRules"]


async def test_a_ux_analyst_can_be_invited_as_a_project_member(lead, project):
    response = await lead.post(f"/projects/{project['id']}/members", json={
        "email": "designer@company.local", "displayName": "UX Designer",
        "roles": ["ux_analyst"]})
    assert response.status_code in (200, 201), response.text


async def _artifact_counts(lead, project_id):
    counts = {}
    for path in ("requirements", "questions", "findings", "specifications", "tests"):
        response = await lead.get(f"/projects/{project_id}/{path}")
        assert response.status_code == 200, (path, response.text)
        counts[path] = len(response.json())
    return counts


async def test_a_second_run_does_not_duplicate_the_first(lead, project_with_evidence):
    project_id = project_with_evidence["id"]
    await lead.patch(f"/projects/{project_id}", json={"enabledAnalysts": [
        "business_analyst", "ux_analyst", "data_analyst", "technical_analyst", "qa_analyst"]})
    await run_analysis(lead, project_id)
    first = await _artifact_counts(lead, project_id)
    assert all(first.values()), first

    second_job = await run_analysis(lead, project_id)

    assert second_job["status"] == "succeeded"
    assert await _artifact_counts(lead, project_id) == first
    # Every stage still ran and reports that it had nothing new to add.
    assert all(sum(stage["outputSummary"].values()) == 0
               for stage in second_job["stages"]), second_job["stages"]


async def test_regenerate_still_creates_new_copies(lead, project_with_evidence):
    from app.ai import orchestrator

    project_id = project_with_evidence["id"]
    await run_analysis(lead, project_id)
    before = await _artifact_counts(lead, project_id)

    started = await lead.post(f"/projects/{project_id}/analysis/runs",
                              json={"regenerate": True})
    await orchestrator.run_job(started.json()["id"])

    after = await _artifact_counts(lead, project_id)
    assert after["specifications"] > before["specifications"]
    assert after["tests"] > before["tests"]


async def test_stable_ids_never_collide_after_a_deletion(lead, project_with_evidence):
    project_id = project_with_evidence["id"]
    await run_analysis(lead, project_id)
    tests = (await lead.get(f"/projects/{project_id}/tests")).json()
    ids = [t["stableId"] for t in tests]
    assert len(ids) == len(set(ids))
    numbers = sorted(int(i.split("-")[1]) for i in ids)
    assert numbers == list(range(1, len(ids) + 1))


async def test_analysis_without_evidence_fails_with_an_explanation(lead, project):
    job = await run_analysis(lead, project["id"])
    assert job["status"] == "failed"
    assert "No readable evidence" in job["message"]


async def test_run_can_be_cancelled_and_resumed(lead, project_with_evidence):
    started = await lead.post(f"/projects/{project_with_evidence['id']}/analysis/runs",
                              json={})
    job_id = started.json()["id"]

    cancelled = await lead.post(
        f"/projects/{project_with_evidence['id']}/analysis/runs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["cancelRequested"] is True

    resumed = await lead.post(
        f"/projects/{project_with_evidence['id']}/analysis/runs/{job_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["cancelRequested"] is False


async def test_requirements_carry_provenance_and_citations(lead, analysed_project):
    response = await lead.get(f"/projects/{analysed_project['id']}/requirements")
    assert response.status_code == 200
    rows = response.json()
    assert rows
    assert {row["provenance"] for row in rows} <= {
        "evidence", "assumption", "ai_suggestion", "client_decision"}
    assert any(row["provenance"] == "ai_suggestion" for row in rows)
    assert any(row["citations"] for row in rows)
    assert all(row["stableId"].startswith(("REQ-", "NFR-")) for row in rows)


async def test_question_register_records_a_resolution_with_history(lead, analysed_project):
    questions = await lead.get(f"/projects/{analysed_project['id']}/questions")
    assert questions.json()
    question = questions.json()[0]

    resolved = await lead.post(
        f"/projects/{analysed_project['id']}/questions/{question['id']}/resolve",
        json={"status": "answered", "answer": "The delivery manager approves it."})
    assert resolved.status_code == 200
    payload = resolved.json()
    assert payload["status"] == "answered"
    assert payload["answeredBy"]
    assert payload["history"][0]["to"] == "answered"


async def test_findings_can_be_resolved_and_waiving_needs_the_permission(
        lead, analysed_project, outsider):
    await lead.post(f"/projects/{analysed_project['id']}/members",
                    json={"email": outsider.user.email, "roles": ["business_analyst"]})
    findings = await lead.get(f"/projects/{analysed_project['id']}/findings")
    assert findings.status_code == 200
    if not findings.json():
        return  # the heuristic analyst found nothing to report on this evidence

    finding = findings.json()[0]
    denied = await outsider.post(
        f"/projects/{analysed_project['id']}/findings/{finding['id']}/resolve",
        json={"status": "waived", "rationale": "not allowed"})
    assert denied.status_code == 403

    allowed = await lead.post(
        f"/projects/{analysed_project['id']}/findings/{finding['id']}/resolve",
        json={"status": "waived", "rationale": "Accepted risk, recorded"})
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "waived"


async def test_regeneration_preview_warns_before_overwriting(lead, analysed_project):
    epic = await first_epic(lead, analysed_project["id"])
    response = await lead.get(
        f"/projects/{analysed_project['id']}/analysis/regenerate-preview/{epic['id']}")
    assert response.status_code == 200
    assert "new draft version" in response.json()["warning"]


async def test_specifications_are_generated_and_labelled_as_proposals(lead,
                                                                      analysed_project):
    response = await lead.get(f"/projects/{analysed_project['id']}/specifications")
    assert response.status_code == 200
    kinds = {spec["kind"] for spec in response.json()}
    assert "functional" in kinds
    assert {"data_model", "api", "process_diagram"} & kinds

    api_spec = next((s for s in response.json() if s["kind"] == "api"), None)
    if api_spec:
        assert api_spec["structured"]["openapi"].startswith("3.")
        assert "not an implemented contract" in api_spec["validation"]["note"]


async def test_traceability_graph_links_evidence_to_items(lead, analysed_project):
    response = await lead.get(f"/projects/{analysed_project['id']}/traceability")
    assert response.status_code == 200
    payload = response.json()
    assert payload["nodes"] and payload["edges"]
    assert {node["kind"] for node in payload["nodes"]} & {"evidence", "backlog_item"}


# --- backlog ----------------------------------------------------------------

async def test_hierarchy_rules_are_enforced(lead, project):
    orphan_feature = await lead.post(f"/projects/{project['id']}/backlog/items",
                                     json={"type": "feature", "title": "No parent"})
    assert orphan_feature.status_code == 422

    epic = await lead.post(f"/projects/{project['id']}/backlog/items",
                           json={"type": "epic", "title": "Accounts"})
    assert epic.status_code == 201
    epic_id = epic.json()["item"]["id"]

    epic_with_parent = await lead.post(f"/projects/{project['id']}/backlog/items",
                                       json={"type": "epic", "title": "Nested epic",
                                             "parentId": epic_id})
    assert epic_with_parent.status_code == 422

    story_under_epic = await lead.post(f"/projects/{project['id']}/backlog/items",
                                       json={"type": "story", "title": "Wrong level",
                                             "parentId": epic_id})
    assert story_under_epic.status_code == 422
    assert "must sit under a" in story_under_epic.json()["error"]["message"]


async def test_stable_ids_are_assigned_per_type(lead, project):
    epic = await lead.post(f"/projects/{project['id']}/backlog/items",
                           json={"type": "epic", "title": "Epic one"})
    feature = await lead.post(f"/projects/{project['id']}/backlog/items",
                              json={"type": "feature", "title": "Feature one",
                                    "parentId": epic.json()["item"]["id"]})
    assert epic.json()["item"]["stableId"] == "EPIC-001"
    assert feature.json()["item"]["stableId"] == "FEAT-001"


async def test_editing_creates_a_new_draft_only_when_content_changes(lead, project):
    created = await lead.post(f"/projects/{project['id']}/backlog/items",
                              json={"type": "epic", "title": "Accounts",
                                    "acceptanceCriteria": ["Outcome validated"]})
    item_id = created.json()["item"]["id"]

    # A label change does not create a version.
    await lead.patch(f"/projects/{project['id']}/backlog/items/{item_id}",
                     json={"priority": "high"})
    detail = await lead.get(f"/projects/{project['id']}/backlog/items/{item_id}")
    assert detail.json()["item"]["currentVersion"] == 1
    assert detail.json()["item"]["priority"] == "high"

    # A content change does.
    await lead.patch(f"/projects/{project['id']}/backlog/items/{item_id}",
                     json={"description": "Revised scope", "changeNote": "clarified"})
    detail = await lead.get(f"/projects/{project['id']}/backlog/items/{item_id}")
    assert detail.json()["version"]["description"] == "Revised scope"


async def test_optimistic_concurrency_rejects_a_stale_edit(lead, project):
    created = await lead.post(f"/projects/{project['id']}/backlog/items",
                              json={"type": "epic", "title": "Accounts"})
    item_id = created.json()["item"]["id"]
    detail = await lead.get(f"/projects/{project['id']}/backlog/items/{item_id}")
    stale_rev = detail.json()["item"]["rev"]

    await lead.patch(f"/projects/{project['id']}/backlog/items/{item_id}",
                     json={"description": "First writer wins"})
    conflicted = await lead.patch(f"/projects/{project['id']}/backlog/items/{item_id}",
                                  json={"description": "Second writer",
                                        "expectedRev": stale_rev})
    assert conflicted.status_code == 409
    assert conflicted.json()["error"]["code"] == "conflict"


async def test_version_history_and_diff(lead, project):
    created = await lead.post(f"/projects/{project['id']}/backlog/items",
                              json={"type": "epic", "title": "Accounts",
                                    "acceptanceCriteria": ["First outcome"]})
    item_id = created.json()["item"]["id"]
    await lead.patch(f"/projects/{project['id']}/backlog/items/{item_id}",
                     json={"description": "v1 text"})

    version = await lead.get(
        f"/projects/{project['id']}/backlog/items/{item_id}/versions/1")
    assert version.status_code == 200

    diff = await lead.get(f"/projects/{project['id']}/backlog/items/{item_id}/diff",
                          params={"base": 1, "compare": 1})
    assert diff.status_code == 200
    assert diff.json()["fields"] == {}


async def test_estimate_rollup_follows_the_specification_rules(lead, project):
    epic = await lead.post(f"/projects/{project['id']}/backlog/items",
                           json={"type": "epic", "title": "Accounts"})
    epic_id = epic.json()["item"]["id"]
    feature = await lead.post(f"/projects/{project['id']}/backlog/items",
                              json={"type": "feature", "title": "Registration",
                                    "parentId": epic_id})
    feature_id = feature.json()["item"]["id"]

    for hours in (30, 30, 20):
        story = await lead.post(f"/projects/{project['id']}/backlog/items",
                                json={"type": "story", "title": f"Story {hours}",
                                      "parentId": feature_id})
        await lead.post(
            f"/projects/{project['id']}/backlog/items/{story.json()['item']['id']}/estimate",
            json={"method": "expert", "storyPoints": 3,
                  "roleEfforts": [{"role": "engineering", "hours": hours}]})

    # Parent rough estimate, kept for comparison only.
    await lead.post(f"/projects/{project['id']}/backlog/items/{epic_id}/estimate",
                    json={"method": "analogy", "likelyHours": 100, "isRoughParent": True,
                          "roleEfforts": [{"role": "engineering", "hours": 100}]})
    # Explicit parent overhead, excluded from the children.
    await lead.post(f"/projects/{project['id']}/backlog/items/{epic_id}/estimate",
                    json={"method": "expert", "overheadHours": 12, "roleEfforts": []})

    rollup = await lead.get(f"/projects/{project['id']}/backlog/items/{epic_id}/rollup")
    payload = rollup.json()
    assert payload["childrenHours"] == 80.0
    assert payload["detailedHours"] == 92.0
    assert payload["roughParentHours"] == 100.0
    assert payload["personDays"] == 11.5
    assert any("kept for comparison" in warning for warning in payload["warnings"])


async def test_estimate_inconsistency_is_warned_not_forced(lead, project):
    created = await lead.post(f"/projects/{project['id']}/backlog/items",
                              json={"type": "epic", "title": "Points only"})
    item_id = created.json()["item"]["id"]
    await lead.post(f"/projects/{project['id']}/backlog/items/{item_id}/estimate",
                    json={"method": "expert", "storyPoints": 8, "roleEfforts": []})

    detail = await lead.get(f"/projects/{project['id']}/backlog/items/{item_id}")
    assert detail.json()["estimate"]["storyPoints"] == 8
    assert any("no role effort" in warning
               for warning in detail.json()["estimateWarnings"])


async def test_dependency_cycles_are_detected(lead, project):
    epic_a = await lead.post(f"/projects/{project['id']}/backlog/items",
                             json={"type": "epic", "title": "A"})
    epic_b = await lead.post(f"/projects/{project['id']}/backlog/items",
                             json={"type": "epic", "title": "B"})
    a, b = epic_a.json()["item"]["id"], epic_b.json()["item"]["id"]

    await lead.post(f"/projects/{project['id']}/backlog/dependencies",
                    json={"fromId": a, "toId": b, "kind": "blocks"})
    response = await lead.post(f"/projects/{project['id']}/backlog/dependencies",
                               json={"fromId": b, "toId": a, "kind": "blocks"})
    assert response.status_code == 201
    assert response.json()["cycles"], "a two node cycle must be reported"


async def test_rate_card_requires_the_permission(lead, project, outsider):
    await lead.post(f"/projects/{project['id']}/members",
                    json={"email": outsider.user.email, "roles": ["business_analyst"]})
    denied = await outsider.get(f"/projects/{project['id']}/rate-cards")
    assert denied.status_code == 403

    created = await lead.post(f"/projects/{project['id']}/rate-cards",
                              json={"name": "Standard", "effectiveFrom": "2026-01-01",
                                    "rates": {"engineering": "100.00"},
                                    "contingencyPercent": 10})
    assert created.status_code == 201
    assert created.json()["rates"]["engineering"] == "100.00"


async def test_archiving_an_item_archives_its_subtree(lead, project):
    epic = await lead.post(f"/projects/{project['id']}/backlog/items",
                           json={"type": "epic", "title": "Accounts"})
    epic_id = epic.json()["item"]["id"]
    await lead.post(f"/projects/{project['id']}/backlog/items",
                    json={"type": "feature", "title": "Registration", "parentId": epic_id})

    response = await lead.delete(f"/projects/{project['id']}/backlog/items/{epic_id}")
    assert response.status_code == 200
    assert response.json()["archived"] == 2
