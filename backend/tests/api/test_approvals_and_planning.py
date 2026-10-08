"""Approval, baseline, planning and chart functionality (sections 10 and 12)."""
from __future__ import annotations

from tests.support import approve_subtree, first_epic


async def _small_tree(lead, project_id: str) -> dict[str, str]:
    epic = await lead.post(f"/projects/{project_id}/backlog/items",
                           json={"type": "epic", "title": "Accounts",
                                 "acceptanceCriteria": ["The outcome is validated"]})
    epic_id = epic.json()["item"]["id"]
    feature = await lead.post(f"/projects/{project_id}/backlog/items",
                              json={"type": "feature", "title": "Registration",
                                    "parentId": epic_id,
                                    "acceptanceCriteria": ["The outcome is demonstrated"]})
    feature_id = feature.json()["item"]["id"]
    story = await lead.post(f"/projects/{project_id}/backlog/items",
                            json={"type": "story", "title": "Customer registers",
                                  "parentId": feature_id,
                                  "acceptanceCriteria": ["A customer can register"]})
    story_id = story.json()["item"]["id"]
    await lead.post(f"/projects/{project_id}/tests",
                    json={"title": "Registration works", "storyId": story_id})
    return {"epic": epic_id, "feature": feature_id, "story": story_id}


# --- approvals --------------------------------------------------------------

async def test_inbox_lists_items_awaiting_a_decision(lead, project):
    await _small_tree(lead, project["id"])
    response = await lead.get(f"/projects/{project['id']}/approvals/inbox")
    assert response.status_code == 200
    payload = response.json()
    assert payload["pendingCount"] >= 3
    assert payload["canDecide"] is True
    assert payload["canWaive"] is True


async def test_preview_shows_the_exact_manifest_with_totals_and_blockers(lead, project):
    ids = await _small_tree(lead, project["id"])
    response = await lead.post(f"/projects/{project['id']}/approvals/preview/{ids['epic']}")
    assert response.status_code == 200
    manifest = response.json()

    assert manifest["counts"]["epic"] == 1
    assert manifest["counts"]["feature"] == 1
    assert manifest["counts"]["story"] == 1
    assert manifest["counts"]["test_case"] == 1
    assert manifest["manifestHash"]
    assert "unit" in manifest["estimateTotals"]
    explicit = [e for e in manifest["entries"] if not e["inherited"]]
    assert len(explicit) == 1 and explicit[0]["itemId"] == ids["epic"]


async def test_approval_cascades_to_descendants(lead, project):
    ids = await _small_tree(lead, project["id"])
    response = await approve_subtree(lead, project["id"], ids["epic"])
    assert response.status_code == 201, response.text
    event = response.json()
    assert event["committed"] is True
    assert len(event["entries"]) == 4

    for key in ("epic", "feature", "story"):
        detail = await lead.get(f"/projects/{project['id']}/backlog/items/{ids[key]}")
        assert detail.json()["item"]["approvedVersion"] == 1
        assert detail.json()["item"]["state"] == "approved"


async def test_stale_manifest_hash_is_refused(lead, project):
    ids = await _small_tree(lead, project["id"])
    preview = await lead.post(f"/projects/{project['id']}/approvals/preview/{ids['epic']}")
    manifest = preview.json()

    await lead.patch(f"/projects/{project['id']}/backlog/items/{ids['story']}",
                     json={"description": "Edited after the preview"})

    response = await lead.post(f"/projects/{project['id']}/approvals/decisions",
                               json={"manifestId": manifest["id"],
                                     "manifestHash": manifest["manifestHash"],
                                     "decision": "approve", "waivers": []})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "version_conflict"
    assert "refreshedManifestId" in response.json()["error"]["details"]

    inbox = await lead.get(f"/projects/{project['id']}/approvals/inbox")
    assert all(row["approvedVersion"] is None for row in inbox.json()["candidates"])


async def test_blockers_must_be_resolved_or_waived_with_a_rationale(lead, project):
    epic = await lead.post(f"/projects/{project['id']}/backlog/items",
                           json={"type": "epic", "title": "Untested",
                                 "acceptanceCriteria": ["Outcome"]})
    epic_id = epic.json()["item"]["id"]
    feature = await lead.post(f"/projects/{project['id']}/backlog/items",
                              json={"type": "feature", "title": "Feature",
                                    "parentId": epic_id,
                                    "acceptanceCriteria": ["Outcome"]})
    await lead.post(f"/projects/{project['id']}/backlog/items",
                    json={"type": "story", "title": "Story without a test",
                          "parentId": feature.json()["item"]["id"],
                          "acceptanceCriteria": ["Observable outcome"]})

    preview = await lead.post(f"/projects/{project['id']}/approvals/preview/{epic_id}")
    kinds = {blocker["kind"] for blocker in preview.json()["blockers"]}
    assert "untestable_requirement" in kinds

    refused = await lead.post(f"/projects/{project['id']}/approvals/decisions",
                              json={"manifestId": preview.json()["id"],
                                    "manifestHash": preview.json()["manifestHash"],
                                    "decision": "approve", "waivers": []})
    assert refused.status_code == 409
    assert refused.json()["error"]["details"]["blockers"]

    empty_rationale = await approve_subtree(
        lead, project["id"], epic_id,
        waivers=[{"blockerKind": "untestable_requirement", "rationale": "   "}])
    assert empty_rationale.status_code == 409

    accepted = await approve_subtree(lead, project["id"], epic_id)
    assert accepted.status_code == 201
    assert accepted.json()["waivers"][0]["rationale"]


async def test_a_later_change_requires_renewed_approval(lead, project):
    ids = await _small_tree(lead, project["id"])
    await approve_subtree(lead, project["id"], ids["epic"])

    await lead.post(f"/projects/{project['id']}/backlog/items",
                    json={"type": "story", "title": "Late addition",
                          "parentId": ids["feature"],
                          "acceptanceCriteria": ["New observable outcome"]})

    epic = await lead.get(f"/projects/{project['id']}/backlog/items/{ids['epic']}")
    assert epic.json()["item"]["requiresReapproval"] is True

    inbox = await lead.get(f"/projects/{project['id']}/approvals/inbox")
    stable_ids = {row["stableId"] for row in inbox.json()["candidates"]}
    assert "EPIC-001" in stable_ids


async def test_revocation_returns_items_to_draft(lead, project):
    ids = await _small_tree(lead, project["id"])
    event = (await approve_subtree(lead, project["id"], ids["epic"])).json()

    response = await lead.post(
        f"/projects/{project['id']}/approvals/events/{event['id']}/revoke",
        json={"reason": "Client withdrew the scope", "itemIds": []})
    assert response.status_code == 200
    assert response.json()["revoked"] is True

    story = await lead.get(f"/projects/{project['id']}/backlog/items/{ids['story']}")
    assert story.json()["item"]["approvedVersion"] is None
    assert story.json()["item"]["requiresReapproval"] is True


async def test_approval_history_records_explicit_and_inherited(lead, project):
    ids = await _small_tree(lead, project["id"])
    await approve_subtree(lead, project["id"], ids["epic"])

    response = await lead.get(f"/projects/{project['id']}/approvals/events")
    assert response.status_code == 200
    event = response.json()[0]
    assert sum(1 for e in event["entries"] if not e["inherited"]) == 1
    assert sum(1 for e in event["entries"] if e["inherited"]) == 3


# --- baselines and change requests ------------------------------------------

async def test_baseline_snapshot_and_comparison(lead, project):
    ids = await _small_tree(lead, project["id"])
    await lead.post(f"/projects/{project['id']}/backlog/items/{ids['story']}/estimate",
                    json={"method": "expert", "storyPoints": 5,
                          "roleEfforts": [{"role": "engineering", "hours": 10}]})

    created = await lead.post(f"/projects/{project['id']}/baselines",
                              json={"name": "Baseline 1"})
    assert created.status_code == 201
    baseline = created.json()
    assert baseline["totals"]["detailedHours"] == 10.0
    assert baseline["locked"] is True

    await lead.post(f"/projects/{project['id']}/backlog/items",
                    json={"type": "story", "title": "Added after the baseline",
                          "parentId": ids["feature"]})

    comparison = await lead.get(
        f"/projects/{project['id']}/baselines/{baseline['id']}/compare")
    assert comparison.status_code == 200
    assert len(comparison.json()["added"]) == 1
    assert comparison.json()["delta"]["items"] == 1


async def test_change_request_decision_marks_affected_items(lead, project):
    ids = await _small_tree(lead, project["id"])
    await approve_subtree(lead, project["id"], ids["epic"])

    created = await lead.post(f"/projects/{project['id']}/change-requests",
                              json={"title": "Add multi company invoices",
                                    "reason": "Client clarified the scope",
                                    "affectedItemIds": [ids["story"]],
                                    "effortDeltaHours": 16, "dateImpactDays": 5})
    assert created.status_code == 201
    assert created.json()["stableId"] == "CR-001"

    decided = await lead.post(
        f"/projects/{project['id']}/change-requests/{created.json()['id']}/decide",
        json={"status": "approved", "decisionNote": "Agreed at the steering meeting"})
    assert decided.status_code == 200

    story = await lead.get(f"/projects/{project['id']}/backlog/items/{ids['story']}")
    assert story.json()["item"]["requiresReapproval"] is True


# --- planning ---------------------------------------------------------------

async def test_iteration_and_board_lifecycle(lead, project):
    iteration = await lead.post(f"/projects/{project['id']}/iterations",
                                json={"name": "Sprint 1", "goal": "Foundations",
                                      "startDate": "2026-03-02", "endDate": "2026-03-13",
                                      "capacityHours": 240})
    assert iteration.status_code == 201

    board = await lead.get(f"/projects/{project['id']}/board/state")
    assert board.status_code == 200
    columns = {column["key"] for column in board.json()["columns"]}
    assert {"backlog", "in_progress", "done"} <= columns
    assert "separately from artifact approval" in board.json()["note"]


async def test_work_in_progress_limit_is_reported(lead, project):
    ids = await _small_tree(lead, project["id"])
    board = await lead.get(f"/projects/{project['id']}/board")
    columns = board.json()["columns"]
    for column in columns:
        if column["key"] == "in_progress":
            column["wipLimit"] = 0
    await lead.put(f"/projects/{project['id']}/board", json={"columns": columns})

    await lead.patch(f"/projects/{project['id']}/backlog/items/{ids['story']}",
                     json={"executionStatus": "in_progress", "kanbanColumn": "in_progress"})
    state = await lead.get(f"/projects/{project['id']}/board/state")
    in_progress = next(c for c in state.json()["columns"] if c["key"] == "in_progress")
    assert in_progress["count"] == 1
    assert in_progress["overLimit"] is True


async def test_time_entries_need_approval_before_counting(lead, project):
    entry = await lead.post(f"/projects/{project['id']}/worklogs",
                            json={"workDate": "2026-03-03", "hours": 6,
                                  "role": "engineering", "note": "analysis"})
    assert entry.status_code == 201
    assert entry.json()["approved"] is False

    rejected = await lead.post(f"/projects/{project['id']}/worklogs",
                               json={"workDate": "2026-03-03", "hours": 0})
    assert rejected.status_code == 409

    approved = await lead.post(
        f"/projects/{project['id']}/worklogs/{entry.json()['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["approved"] is True


async def test_capacity_reports_availability(lead, project):
    response = await lead.get(f"/projects/{project['id']}/capacity",
                              params={"start": "2026-03-02", "end": "2026-03-06"})
    assert response.status_code == 200
    row = response.json()[0]
    assert row["scheduledHours"] == 40.0
    assert row["availableHours"] <= row["scheduledHours"]


async def test_charts_expose_definition_units_and_freshness(lead, analysed_project):
    for chart in ["planned_vs_actual", "quality_scope", "cumulative_flow",
                  "cycle_time", "velocity", "milestones"]:
        response = await lead.get(f"/projects/{analysed_project['id']}/charts/{chart}")
        assert response.status_code == 200, chart
        payload = response.json()
        assert payload["definition"], chart
        assert payload["unit"], chart
        assert payload["asOf"], chart
        assert payload["dataFreshness"], chart


async def test_burndown_requires_an_iteration_and_honours_the_unit(lead, project):
    missing = await lead.get(f"/projects/{project['id']}/charts/burndown")
    assert missing.status_code == 409

    iteration = await lead.post(f"/projects/{project['id']}/iterations",
                                json={"name": "Sprint 1", "startDate": "2026-03-02",
                                      "endDate": "2026-03-13"})
    response = await lead.get(f"/projects/{project['id']}/charts/burndown",
                              params={"iteration_id": iteration.json()["id"],
                                      "unit": "person_hours"})
    assert response.status_code == 200
    assert response.json()["unit"] == "person_hours"
    assert "never mixed" in response.json()["definition"]


async def test_cost_summary_is_permission_gated(lead, project, outsider):
    await lead.post(f"/projects/{project['id']}/members",
                    json={"email": outsider.user.email, "roles": ["business_analyst"]})
    assert (await outsider.get(f"/projects/{project['id']}/cost-summary")).status_code == 403
    assert (await outsider.get(f"/projects/{project['id']}/charts/cost")).status_code == 403

    allowed = await lead.get(f"/projects/{project['id']}/cost-summary")
    assert allowed.status_code == 200
    assert allowed.json()["currency"] == "EUR"


async def test_unknown_chart_is_a_clean_404(lead, project):
    response = await lead.get(f"/projects/{project['id']}/charts/not_a_chart")
    assert response.status_code == 404


async def _card(lead, project_id: str, item_id: str) -> tuple[str, dict]:
    state = (await lead.get(f"/projects/{project_id}/board/state")).json()
    for column in state["columns"]:
        for card in column["items"]:
            if card["id"] == item_id:
                return column["key"], card
    raise AssertionError("card not on the board")


async def test_moving_a_card_sets_the_status_from_its_column(lead, project):
    ids = await _small_tree(lead, project["id"])
    column, card = await _card(lead, project["id"], ids["story"])
    assert column == "backlog" and card["executionStatus"] == "not_started"

    moved = await lead.post(f"/projects/{project['id']}/board/move", json={
        "itemId": ids["story"], "columnKey": "in_review", "expectedRev": card["rev"]})

    assert moved.status_code == 200, moved.text
    assert moved.json()["item"]["executionStatus"] == "in_review"
    assert moved.json()["warning"] is None
    column, card = await _card(lead, project["id"], ids["story"])
    assert column == "in_review" and card["executionStatus"] == "in_review"

    # Delivery state only: the item's approval and content are untouched.
    item = (await lead.get(f"/projects/{project['id']}/backlog/items/{ids['story']}")).json()
    assert item["item"]["requiresReapproval"] is False
    assert item["item"]["currentVersion"] == 1


async def test_a_stale_move_is_refused(lead, project):
    ids = await _small_tree(lead, project["id"])
    _, card = await _card(lead, project["id"], ids["story"])
    first = await lead.post(f"/projects/{project['id']}/board/move", json={
        "itemId": ids["story"], "columnKey": "ready", "expectedRev": card["rev"]})
    assert first.status_code == 200

    # Someone else's board still shows the old revision.
    stale = await lead.post(f"/projects/{project['id']}/board/move", json={
        "itemId": ids["story"], "columnKey": "done", "expectedRev": card["rev"]})
    assert stale.status_code == 409
    column, _ = await _card(lead, project["id"], ids["story"])
    assert column == "ready"


async def test_a_move_over_the_wip_limit_is_allowed_and_reported(lead, project):
    ids = await _small_tree(lead, project["id"])
    board = (await lead.get(f"/projects/{project['id']}/board")).json()
    for column in board["columns"]:
        if column["key"] == "in_progress":
            column["wipLimit"] = 0
    await lead.put(f"/projects/{project['id']}/board", json={"columns": board["columns"]})

    moved = await lead.post(f"/projects/{project['id']}/board/move",
                            json={"itemId": ids["story"], "columnKey": "in_progress"})
    assert moved.status_code == 200
    assert "over its WIP limit of 0" in moved.json()["warning"]


async def test_moves_need_a_known_column_and_permission(lead, project, outsider):
    ids = await _small_tree(lead, project["id"])
    unknown = await lead.post(f"/projects/{project['id']}/board/move",
                              json={"itemId": ids["story"], "columnKey": "nowhere"})
    assert unknown.status_code == 404
    epic = await lead.post(f"/projects/{project['id']}/board/move",
                           json={"itemId": ids["epic"], "columnKey": "done"})
    assert epic.status_code == 404
    refused = await outsider.post(f"/projects/{project['id']}/board/move",
                                  json={"itemId": ids["story"], "columnKey": "done"})
    assert refused.status_code in (403, 404)


async def test_new_boards_have_a_blocked_column(lead, project):
    board = (await lead.get(f"/projects/{project['id']}/board")).json()
    assert [c["key"] for c in board["columns"]] == [
        "backlog", "ready", "in_progress", "blocked", "in_review", "done"]
    blocked = next(c for c in board["columns"] if c["key"] == "blocked")
    assert blocked["mapsToStatus"] == "blocked" and blocked["wipLimit"] is None


async def test_a_board_saved_before_blocked_existed_gains_it_once(lead, project):
    from app.repositories import boards

    board = (await lead.get(f"/projects/{project['id']}/board")).json()
    # Simulate a board stored before the Blocked column existed.
    legacy = [c for c in board["columns"] if c["key"] != "blocked"]
    await boards.update(board["id"], {"columns": legacy, "layoutVersion": 1})

    upgraded = (await lead.get(f"/projects/{project['id']}/board")).json()
    assert [c["key"] for c in upgraded["columns"]][2:4] == ["in_progress", "blocked"]

    # A board that removes Blocked on purpose keeps it removed.
    await lead.put(f"/projects/{project['id']}/board", json={"columns": legacy})
    again = (await lead.get(f"/projects/{project['id']}/board")).json()
    assert "blocked" not in [c["key"] for c in again["columns"]]


async def test_blocking_needs_a_reason_and_unblocking_clears_it(lead, project):
    ids = await _small_tree(lead, project["id"])
    refused = await lead.post(f"/projects/{project['id']}/board/move",
                              json={"itemId": ids["story"], "columnKey": "blocked"})
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "blocked_reason_required"

    blocked = await lead.post(f"/projects/{project['id']}/board/move", json={
        "itemId": ids["story"], "columnKey": "blocked",
        "blockedReason": "Waiting for the client's SSO metadata"})
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["item"]["executionStatus"] == "blocked"
    column, card = await _card(lead, project["id"], ids["story"])
    assert column == "blocked"
    assert card["blockedReason"] == "Waiting for the client's SSO metadata"

    resumed = await lead.post(f"/projects/{project['id']}/board/move",
                              json={"itemId": ids["story"], "columnKey": "in_progress"})
    assert resumed.json()["item"]["blockedReason"] is None
    _, card = await _card(lead, project["id"], ids["story"])
    assert card["blockedReason"] is None and card["executionStatus"] == "in_progress"


async def test_flow_counts_a_moved_card_in_the_column_it_moved_to(lead, project):
    ids = await _small_tree(lead, project["id"])
    for key in ("ready", "in_progress"):
        await lead.post(f"/projects/{project['id']}/board/move",
                        json={"itemId": ids["story"], "columnKey": key})

    flow = (await lead.get(f"/projects/{project['id']}/charts/cumulative_flow")).json()
    today = {s["key"]: s["points"][-1]["value"] for s in flow["series"]}
    assert today["in_progress"] == 1
    assert today["ready"] == 0
    assert "blocked" in today


async def test_the_dashboard_counts_blocked_and_started_work(lead, project):
    ids = await _small_tree(lead, project["id"])

    def counts(chart):
        return {p["category"]: p["value"] for p in chart["series"][0]["points"]}

    before = counts((await lead.get(f"/projects/{project['id']}/charts/quality_scope")).json())
    assert before["blocked"] == 0 and before["started"] == 0

    await lead.post(f"/projects/{project['id']}/board/move", json={
        "itemId": ids["story"], "columnKey": "blocked", "blockedReason": "Waiting on access"})
    after = counts((await lead.get(f"/projects/{project['id']}/charts/quality_scope")).json())
    assert after["blocked"] == 1 and after["started"] == 1
