"""Shared helpers and fixtures for API level and acceptance tests.

These tests drive the real FastAPI application over HTTP semantics (ASGI
transport), so they exercise routing, dependency injection, authentication,
authorization, serialisation and error mapping exactly as a browser would — but
against an in memory database, so the suite needs no infrastructure.
"""
from __future__ import annotations

from typing import Any, AsyncIterator

import httpx
import pytest

from app.core.policy import Role
from app.core.security import hash_password
from app.main import app
from app.models.identity import User
from app.repositories import users


@pytest.fixture
async def client(in_memory_db) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://testserver/api/v1") as http:
        yield http


class Actor:
    """A signed in caller. Wraps the client with this actor's bearer token."""

    def __init__(self, http: httpx.AsyncClient, user: User, token: str) -> None:
        self._http = http
        self.user = user
        self.token = token
        self.headers = {"Authorization": f"Bearer {token}"}

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._http.get(url, headers=self.headers, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._http.post(url, headers=self.headers, **kwargs)

    async def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._http.patch(url, headers=self.headers, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._http.put(url, headers=self.headers, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._http.delete(url, headers=self.headers, **kwargs)


async def _sign_in(http: httpx.AsyncClient, email: str, display_name: str, *,
                   global_roles: list[str] | None = None,
                   is_client: bool = False) -> Actor:
    password = "Test!2026"
    existing = await users.find_one({"email": email})
    if existing is None:
        existing = User(email=email, display_name=display_name,
                        password_hash=hash_password(password),
                        global_roles=global_roles or [], is_client=is_client)
        await users.insert(existing)
    response = await http.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return Actor(http, existing, response.json()["accessToken"])


@pytest.fixture
async def lead(client: httpx.AsyncClient) -> Actor:
    """Lead analyst: creates projects, so becomes their project administrator."""
    return await _sign_in(client, "lead@test.local", "Lead Analyst")


@pytest.fixture
async def admin(client: httpx.AsyncClient) -> Actor:
    return await _sign_in(client, "admin@test.local", "System Administrator",
                          global_roles=[str(Role.SYSTEM_ADMIN)])


@pytest.fixture
async def reviewer(client: httpx.AsyncClient) -> Actor:
    """A client reviewer with no project membership until one is granted."""
    return await _sign_in(client, "reviewer@client.example.com", "Client Reviewer",
                          is_client=True)


@pytest.fixture
async def outsider(client: httpx.AsyncClient) -> Actor:
    """An authenticated internal user who is a member of no project."""
    return await _sign_in(client, "outsider@test.local", "Unrelated Colleague")


@pytest.fixture
async def project(lead: Actor) -> dict[str, Any]:
    response = await lead.post("/projects", json={
        "key": "TEST", "name": "Test project", "clientName": "Northwind",
        "languages": ["en", "el"], "outputLanguage": "en",
        "deliveryMethod": "scrum", "defaultClassification": "confidential",
        "currency": "EUR",
    })
    assert response.status_code == 201, response.text
    return response.json()


BRIEF_EN = """# Customer portal brief

## Goal
The goal is to reduce support calls for routine requests.

The system must allow a customer to register with an email address.
The system shall send a verification email before the account becomes active.
Only an administrator shall be able to see other customers' invoices.
The invoice list must load in under 2 seconds for 95 percent of requests.

Decision: the first release covers invoices only.
Open question: it is unclear who approves a deactivation. TBD.
"""

NOTES_EL = """# Σημειώσεις συνάντησης

Ο πελάτης πρέπει να μπορεί να συνδεθεί με κωδικό πρόσβασης.
Κανόνας: εφόσον ο λογαριασμός είναι ανενεργός, δεν επιτρέπεται η πρόσβαση.
Ερώτηση: δεν είναι σαφές ποιος εγκρίνει την απενεργοποίηση. Απαιτείται διευκρίνιση.
"""

SCHEDULE_CSV = """Milestone,Date,Owner
Discovery complete,2026-02-28,Lead Analyst
Release 1,2026-05-15,Delivery Manager
"""


async def upload(actor: Actor, project_id: str, filename: str, body: str, *,
                 kind: str = "brief", authority: str = "working",
                 classification: str | None = None,
                 document_id: str | None = None) -> dict[str, Any]:
    """Upload evidence through the multipart endpoint."""
    import json

    meta = {"title": filename, "kind": kind, "authority": authority}
    if classification:
        meta["classification"] = classification
    data = {"meta": json.dumps(meta)}
    if document_id:
        data["document_id"] = document_id
    response = await actor.post(
        f"/projects/{project_id}/sources",
        files={"file": (filename, body.encode("utf-8"), "text/markdown")},
        data=data)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
async def project_with_evidence(lead: Actor, project: dict[str, Any]) -> dict[str, Any]:
    await upload(lead, project["id"], "brief.md", BRIEF_EN, kind="brief",
                 authority="contractual")
    await upload(lead, project["id"], "notes-el.md", NOTES_EL, kind="meeting_notes")
    await upload(lead, project["id"], "schedule.csv", SCHEDULE_CSV, kind="schedule")
    return project


async def run_analysis(actor: Actor, project_id: str) -> dict[str, Any]:
    """Queue an analysis run and execute it inline (the worker does this in production)."""
    from app.ai import orchestrator

    response = await actor.post(f"/projects/{project_id}/analysis/runs", json={})
    assert response.status_code == 202, response.text
    job = response.json()
    await orchestrator.run_job(job["id"])
    refreshed = await actor.get(f"/projects/{project_id}/analysis/runs/{job['id']}")
    assert refreshed.status_code == 200
    return refreshed.json()


@pytest.fixture
async def analysed_project(lead: Actor, project_with_evidence: dict[str, Any]
                           ) -> dict[str, Any]:
    await run_analysis(lead, project_with_evidence["id"])
    return project_with_evidence


async def first_epic(actor: Actor, project_id: str) -> dict[str, Any]:
    response = await actor.get(f"/projects/{project_id}/backlog/tree")
    assert response.status_code == 200, response.text
    roots = response.json()
    assert roots, "the analysis produced no backlog"
    return roots[0]


async def approve_subtree(actor: Actor, project_id: str, root_id: str, *,
                          waivers: list[dict[str, Any]] | None = None
                          ) -> httpx.Response:
    """Preview then submit an approval for a subtree, waiving listed blockers."""
    preview = await actor.post(f"/projects/{project_id}/approvals/preview/{root_id}")
    assert preview.status_code == 200, preview.text
    manifest = preview.json()
    body: dict[str, Any] = {
        "manifestId": manifest["id"],
        "manifestHash": manifest["manifestHash"],
        "decision": "approve",
    }
    if waivers is None:
        # Waive whatever critical blockers the bundle reports, with a rationale,
        # so the test exercises the recorded waiver path rather than skipping it.
        waivers = [
            {"blockerKind": blocker["kind"], "targetId": blocker.get("targetId"),
             "rationale": "Accepted for the purposes of this automated check"}
            for blocker in manifest["blockers"]
            if blocker["severity"] == "critical" and blocker["waivable"]
        ]
    body["waivers"] = waivers
    return await actor.post(f"/projects/{project_id}/approvals/decisions", json=body)
