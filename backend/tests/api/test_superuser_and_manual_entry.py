"""The platform owner, and creating every kind of entry by hand.

Two related concerns: a single account that owns every project without needing a
membership record, and the ability to author each artifact manually rather than
only through the analyst workflow.
"""
from __future__ import annotations

import pytest

from app.core.policy import Permission, Role, permissions_for
from app.repositories import audit_events
from tests.support import _sign_in, upload

HAND_WRITTEN_GHERKIN = """@negative @high
Feature: Invoice access
  Scenario: Inactive account
    Given an inactive customer account
    When the invoice list is opened
    Then access is refused
"""


@pytest.fixture
async def owner(client):
    """The platform owner: superuser standing, no project membership anywhere."""
    return await _sign_in(client, "owner@test.local", "Platform Owner",
                          global_roles=[str(Role.SUPERUSER)])


# --- the platform owner -----------------------------------------------------

def test_the_owner_role_grants_every_permission():
    granted = permissions_for([Role.SUPERUSER])
    assert granted == set(Permission)
    # The separation the specification draws for the system administrator stands.
    assert Permission.BACKLOG_READ not in permissions_for([Role.SYSTEM_ADMIN])


async def test_the_owner_reads_a_project_it_is_not_a_member_of(lead, project, owner):
    members = await lead.get(f"/projects/{project['id']}/members")
    assert owner.user.id not in {row["userId"] for row in members.json()}

    response = await owner.get(f"/projects/{project['id']}")
    assert response.status_code == 200
    assert response.json()["key"] == "TEST"


async def test_the_owner_sees_every_project_in_the_portfolio(lead, project, owner):
    await lead.post("/projects", json={"key": "SECOND", "name": "Another project"})

    portfolio = await owner.get("/projects")
    assert portfolio.status_code == 200
    assert {row["key"] for row in portfolio.json()} == {"TEST", "SECOND"}


async def test_the_owner_holds_every_project_permission(lead, project, owner):
    """Read, write, cost, audit and administration, with no membership record."""
    for url in [f"/projects/{project['id']}/backlog/tree",
                f"/projects/{project['id']}/sources",
                f"/projects/{project['id']}/cost-summary",
                f"/projects/{project['id']}/rate-cards",
                f"/projects/{project['id']}/audit",
                f"/projects/{project['id']}/egress",
                f"/projects/{project['id']}/integrations",
                f"/projects/{project['id']}/shares",
                f"/projects/{project['id']}/charts/cost"]:
        response = await owner.get(url)
        assert response.status_code == 200, f"{url} returned {response.status_code}"

    created = await owner.post(f"/projects/{project['id']}/backlog/items",
                               json={"type": "epic", "title": "Authored by the owner",
                                     "acceptanceCriteria": ["An observable outcome"]})
    assert created.status_code == 201

    updated = await owner.patch(f"/projects/{project['id']}",
                                json={"clientName": "Renamed by the owner"})
    assert updated.status_code == 200


async def test_the_owner_can_approve_without_being_a_project_approver(lead, project,
                                                                      owner):
    epic = await owner.post(f"/projects/{project['id']}/backlog/items",
                            json={"type": "epic", "title": "Accounts",
                                  "acceptanceCriteria": ["Outcome validated"]})
    epic_id = epic.json()["item"]["id"]
    feature = await owner.post(f"/projects/{project['id']}/backlog/items",
                               json={"type": "feature", "title": "Registration",
                                     "parentId": epic_id,
                                     "acceptanceCriteria": ["Outcome demonstrated"]})
    story = await owner.post(f"/projects/{project['id']}/backlog/items",
                             json={"type": "story", "title": "Customer registers",
                                   "parentId": feature.json()["item"]["id"],
                                   "acceptanceCriteria": ["A customer can register"]})
    await owner.post(f"/projects/{project['id']}/tests",
                     json={"title": "Registration works",
                           "storyId": story.json()["item"]["id"]})

    preview = await owner.post(f"/projects/{project['id']}/approvals/preview/{epic_id}")
    assert preview.status_code == 200
    manifest = preview.json()
    decision = await owner.post(f"/projects/{project['id']}/approvals/decisions",
                                json={"manifestId": manifest["id"],
                                      "manifestHash": manifest["manifestHash"],
                                      "decision": "approve", "waivers": []})
    assert decision.status_code == 201
    assert decision.json()["committed"] is True


async def test_owner_access_to_a_foreign_project_is_audited(lead, project, owner):
    await owner.get(f"/projects/{project['id']}")

    events = await audit_events.list({"projectId": project["id"],
                                      "action": "project.accessed_as_owner"})
    assert events, "reaching a project you do not belong to must be recorded"
    assert events[0].actor_id == owner.user.id
    assert events[0].detail["standing"] == "superuser"


async def test_the_owner_administers_the_deployment(owner):
    assert (await owner.get("/admin/models")).status_code == 200
    assert (await owner.get("/admin/users")).status_code == 200
    assert (await owner.get("/admin/jobs")).status_code == 200


async def test_ownership_can_be_granted_and_is_recorded(admin, owner, outsider):
    promoted = await admin.patch(f"/admin/users/{outsider.user.id}",
                                 json={"globalRoles": [str(Role.SUPERUSER)]})
    assert promoted.status_code == 200
    assert promoted.json()["globalRoles"] == ["superuser"]

    events = await audit_events.list({"action": "admin.user_updated"})
    assert events[0].detail["grantedSuperuser"] is True


async def test_an_unknown_platform_role_is_refused(admin, outsider):
    response = await admin.patch(f"/admin/users/{outsider.user.id}",
                                 json={"globalRoles": ["root"]})
    assert response.status_code == 422
    assert response.json()["error"]["details"]["unknown"] == ["root"]


async def test_the_last_owner_cannot_remove_their_own_standing(client, owner):
    response = await owner.patch(f"/admin/users/{owner.user.id}",
                                 json={"globalRoles": []})
    assert response.status_code == 409
    assert "only active platform owner" in response.json()["error"]["message"]

    # With a second owner in place the handover is allowed.
    second = await _sign_in(client, "owner2@test.local", "Second Owner",
                            global_roles=[str(Role.SUPERUSER)])
    assert second.user.id
    allowed = await owner.patch(f"/projects/../../admin/users/{owner.user.id}"
                                .replace("/projects/../..", ""),
                                json={"globalRoles": []})
    assert allowed.status_code == 200


async def test_ownership_does_not_make_a_client_an_owner(lead, project, reviewer):
    """The client path is unaffected by the existence of the owner role."""
    await lead.post(f"/projects/{project['id']}/members",
                    json={"email": reviewer.user.email, "roles": ["client_reviewer"]})
    assert (await reviewer.get(f"/projects/{project['id']}")).status_code == 403
    assert (await reviewer.get("/admin/users")).status_code == 403


# --- manual entry -----------------------------------------------------------

async def test_a_requirement_can_be_written_by_hand(lead, project):
    response = await lead.post(f"/projects/{project['id']}/requirements",
                               json={"type": "business_rule",
                                     "title": "Inactive accounts cannot see invoices",
                                     "statement": "If the account is inactive, access "
                                                  "to invoices is refused.",
                                     "provenance": "evidence",
                                     "priority": "high", "confidence": 0.9})
    assert response.status_code == 201
    created = response.json()
    assert created["stableId"] == "REQ-001"
    assert created["provenance"] == "evidence"
    assert created["state"] == "draft"


async def test_a_question_can_be_raised_by_hand(lead, project):
    response = await lead.post(f"/projects/{project['id']}/questions",
                               json={"kind": "missing_rule", "severity": "critical",
                                     "title": "Who approves a deactivation?",
                                     "detail": "The brief does not say.",
                                     "proposedClarification": "Name the approver role.",
                                     "clientVisible": True})
    assert response.status_code == 201
    assert response.json()["stableId"] == "Q-001"
    assert response.json()["status"] == "open"


async def test_glossary_terms_are_added_and_deduplicated(lead, project):
    created = await lead.post(f"/projects/{project['id']}/glossary",
                              json={"term": "Invoice",
                                    "definition": "A billing document issued monthly.",
                                    "language": "en",
                                    "translations": {"el": "Τιμολόγιο"}})
    assert created.status_code == 201
    assert created.json()["translations"]["el"] == "Τιμολόγιο"

    duplicate = await lead.post(f"/projects/{project['id']}/glossary",
                                json={"term": "Invoice", "definition": "Again"})
    assert duplicate.status_code == 409

    listed = await lead.get(f"/projects/{project['id']}/glossary")
    assert [row["term"] for row in listed.json()] == ["Invoice"]

    deleted = await lead.delete(
        f"/projects/{project['id']}/glossary/{created.json()['id']}")
    assert deleted.status_code == 200
    assert (await lead.get(f"/projects/{project['id']}/glossary")).json() == []


async def test_a_specification_can_be_authored_by_hand(lead, project):
    response = await lead.post(f"/projects/{project['id']}/specifications",
                               json={"kind": "functional",
                                     "title": "Invoice list behaviour",
                                     "body": "## Scope\\n\\nThe list shows 24 months."})
    assert response.status_code == 201
    spec = response.json()
    assert spec["version"] == 1
    assert spec["state"] == "draft"
    assert spec["generatedByRole"] is None, "a hand written spec has no generating role"

    listed = await lead.get(f"/projects/{project['id']}/specifications",
                            params={"kind": "functional"})
    assert [row["id"] for row in listed.json()] == [spec["id"]]


async def test_a_process_diagram_can_be_authored_by_hand(lead, project):
    response = await lead.post(f"/projects/{project['id']}/specifications",
                               json={"kind": "process_diagram", "title": "Sign in flow",
                                     "diagramSource": "flowchart TD\\n  a-->b"})
    assert response.status_code == 201
    assert response.json()["diagramSource"].startswith("flowchart")


async def test_evidence_can_be_linked_to_an_artifact_by_hand(lead, project):
    source = await upload(lead, project["id"], "brief.md",
                          "# Brief\\n\\nThe system must refuse inactive accounts.")
    requirement = await lead.post(f"/projects/{project['id']}/requirements",
                                  json={"title": "Refuse inactive accounts",
                                        "statement": "Inactive accounts are refused."})
    requirement_id = requirement.json()["id"]

    linked = await lead.post(f"/projects/{project['id']}/evidence-links",
                             json={"sourceVersionId": source["currentVersionId"],
                                   "locatorKind": "paragraph",
                                   "locatorValue": "Brief#p2",
                                   "targetType": "requirement",
                                   "targetId": requirement_id,
                                   "rationale": "States the rule directly"})
    assert linked.status_code == 201
    assert linked.json()["createdBy"] == lead.user.id

    trace = await lead.get(f"/projects/{project['id']}/traceability",
                           params={"target_id": requirement_id})
    assert trace.json()["edges"], "the manual link appears in the traceability graph"

    removed = await lead.delete(
        f"/projects/{project['id']}/evidence-links/{linked.json()['id']}")
    assert removed.status_code == 200


async def test_linking_to_evidence_outside_the_project_is_refused(lead, project):
    requirement = await lead.post(f"/projects/{project['id']}/requirements",
                                  json={"title": "A requirement",
                                        "statement": "Something must happen."})
    response = await lead.post(f"/projects/{project['id']}/evidence-links",
                               json={"sourceVersionId": "not-in-this-project",
                                     "targetType": "requirement",
                                     "targetId": requirement.json()["id"]})
    assert response.status_code == 404


async def test_manual_entry_requires_the_editing_permission(lead, project, outsider):
    await lead.post(f"/projects/{project['id']}/members",
                    json={"email": outsider.user.email, "roles": ["internal_viewer"]})

    for url, body in [
        (f"/projects/{project['id']}/requirements",
         {"title": "x", "statement": "y"}),
        (f"/projects/{project['id']}/questions", {"title": "x", "detail": "y"}),
        (f"/projects/{project['id']}/glossary", {"term": "x", "definition": "y"}),
        (f"/projects/{project['id']}/specifications",
         {"kind": "functional", "title": "x"}),
    ]:
        response = await outsider.post(url, json=body)
        assert response.status_code == 403, url


async def test_a_test_case_can_be_written_by_hand_with_gherkin(lead, project):
    story = await lead.post(f"/projects/{project['id']}/backlog/items",
                            json={"type": "epic", "title": "Container"})
    assert story.status_code == 201

    response = await lead.post(f"/projects/{project['id']}/tests", json={
        "title": "Inactive account cannot open invoices",
        "objective": "Access is refused for an inactive account.",
        "testType": "negative", "priority": "high",
        "preconditions": ["An inactive customer account"],
        "steps": [{"ordinal": 1, "action": "Open the invoice list",
                   "expected": "Access is refused"}],
        "expectedResults": ["Access is refused", "No invoice data is returned"],
        "gherkinText": HAND_WRITTEN_GHERKIN,
    })
    assert response.status_code == 201
    created = response.json()
    assert created["stableId"] == "TC-001"
    assert created["reviewState"] == "pending_review"
    assert created["gherkin"]["scenarios"][0]["name"] == "Inactive account"


async def test_planning_entries_can_be_added_by_hand(lead, project):
    sprint = await lead.post(f"/projects/{project['id']}/iterations",
                             json={"name": "Sprint 1", "goal": "Foundations",
                                   "startDate": "2026-03-02", "endDate": "2026-03-13",
                                   "capacityHours": 240})
    assert sprint.status_code == 201

    milestone = await lead.post(f"/projects/{project['id']}/milestones",
                                json={"name": "Release 1", "dueDate": "2026-05-15",
                                      "baselineDate": "2026-05-01"})
    assert milestone.status_code == 201

    allocation = await lead.post(f"/projects/{project['id']}/allocations",
                                 json={"userId": lead.user.id, "role": "analysis",
                                       "startDate": "2026-03-02",
                                       "endDate": "2026-03-13", "percent": 60})
    assert allocation.status_code == 201
    assert allocation.json()["allocation"]["percent"] == 60

    card = await lead.post(f"/projects/{project['id']}/rate-cards",
                           json={"name": "Standard", "effectiveFrom": "2026-01-01",
                                 "rates": {"analysis": "85.00"}})
    assert card.status_code == 201
