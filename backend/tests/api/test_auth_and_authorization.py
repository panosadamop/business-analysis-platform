"""Authentication and server side authorization (specification section 4)."""
from __future__ import annotations

from app.core.utils import utcnow
from app.repositories import members


async def test_unauthenticated_requests_are_refused(client):
    for method, url in [("GET", "/projects"), ("GET", "/auth/me"),
                        ("POST", "/projects")]:
        response = await client.request(method, url, json={})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"


async def test_wrong_password_and_unknown_account_are_indistinguishable(client, lead):
    unknown = await client.post("/auth/login",
                                json={"email": "nobody@test.local", "password": "x"})
    wrong = await client.post("/auth/login",
                              json={"email": lead.user.email, "password": "wrong"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]


async def test_malformed_token_is_refused(client):
    response = await client.get("/auth/me",
                                headers={"Authorization": "Bearer not-a-token"})
    assert response.status_code == 401


async def test_auth_providers_are_discoverable(client):
    response = await client.get("/auth/providers")
    assert response.status_code == 200
    payload = response.json()
    assert payload["local"] is True
    assert "oidc" in payload


async def test_project_creator_becomes_project_administrator(lead, project):
    response = await lead.get(f"/projects/{project['id']}/members")
    assert response.status_code == 200
    roles = response.json()[0]["roles"]
    assert "project_admin" in roles


async def test_a_non_member_cannot_discover_a_project(outsider, project):
    """Existence is not leaked: a non member gets 404, not 403."""
    response = await outsider.get(f"/projects/{project['id']}")
    assert response.status_code == 404
    listing = await outsider.get("/projects")
    assert listing.json() == []


async def test_client_reviewer_is_refused_every_internal_surface(lead, project, reviewer):
    await lead.post(f"/projects/{project['id']}/members",
                    json={"email": reviewer.user.email, "roles": ["client_reviewer"]})
    for url in [f"/projects/{project['id']}",
                f"/projects/{project['id']}/backlog/tree",
                f"/projects/{project['id']}/cost-summary",
                f"/projects/{project['id']}/sources",
                f"/projects/{project['id']}/findings",
                f"/projects/{project['id']}/audit"]:
        response = await reviewer.get(url)
        assert response.status_code == 403, f"{url} returned {response.status_code}"


async def test_contributor_cannot_edit_the_backlog_or_read_cost(lead, project, outsider):
    await lead.post(f"/projects/{project['id']}/members",
                    json={"email": outsider.user.email, "roles": ["contributor"]})

    read = await outsider.get(f"/projects/{project['id']}/backlog/tree")
    assert read.status_code == 200

    write = await outsider.post(f"/projects/{project['id']}/backlog/items",
                                json={"type": "epic", "title": "Not allowed"})
    assert write.status_code == 403
    assert write.json()["error"]["details"]["missing"] == ["backlog.edit"]

    cost = await outsider.get(f"/projects/{project['id']}/cost-summary")
    assert cost.status_code == 403


async def test_qa_analyst_may_edit_tests_but_not_approve(lead, project, outsider):
    await lead.post(f"/projects/{project['id']}/members",
                    json={"email": outsider.user.email, "roles": ["qa_analyst"]})
    created = await outsider.post(f"/projects/{project['id']}/tests",
                                  json={"title": "A QA authored case"})
    assert created.status_code == 201

    epic = await lead.post(f"/projects/{project['id']}/backlog/items",
                           json={"type": "epic", "title": "Epic",
                                 "acceptanceCriteria": ["Outcome"]})
    decision = await outsider.post(f"/projects/{project['id']}/approvals/decisions",
                                   json={"manifestId": "x", "manifestHash": "y"})
    assert decision.status_code == 403
    assert epic.status_code == 201


async def test_system_administrator_has_no_implicit_content_access(admin, project):
    """Infrastructure administration is not a project entitlement."""
    assert (await admin.get("/admin/models")).status_code == 200
    backlog = await admin.get(f"/projects/{project['id']}/backlog/tree")
    assert backlog.status_code == 403


async def test_revoked_membership_loses_access_immediately(lead, project, outsider):
    created = await lead.post(f"/projects/{project['id']}/members",
                              json={"email": outsider.user.email,
                                    "roles": ["business_analyst"]})
    member_id = created.json()["id"]
    assert (await outsider.get(f"/projects/{project['id']}/backlog/tree")).status_code == 200

    await lead.patch(f"/projects/{project['id']}/members/{member_id}",
                     json={"revoked": True})
    response = await outsider.get(f"/projects/{project['id']}/backlog/tree")
    assert response.status_code == 403
    assert "revoked" in response.json()["error"]["message"].lower()


async def test_expired_membership_loses_access(lead, project, outsider):
    created = await lead.post(f"/projects/{project['id']}/members",
                              json={"email": outsider.user.email,
                                    "roles": ["business_analyst"]})
    await members.update(created.json()["id"],
                         {"expiresAt": utcnow().replace(year=utcnow().year - 1)})
    response = await outsider.get(f"/projects/{project['id']}/backlog/tree")
    assert response.status_code == 403
    assert "expired" in response.json()["error"]["message"].lower()


async def test_errors_use_the_documented_structure(lead, project):
    response = await lead.get(f"/projects/{project['id']}/backlog/items/missing")
    assert response.status_code == 404
    payload = response.json()["error"]
    assert set(payload) == {"code", "message", "details"}
    assert payload["code"] == "not_found"


async def test_responses_carry_a_correlation_id(client):
    response = await client.get("/auth/providers")
    assert response.headers.get("x-correlation-id")
