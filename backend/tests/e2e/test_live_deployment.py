"""End to end checks against a running deployment.

These are the tests that exercise the real stack: a real MongoDB replica set,
the real worker process, the real web tier. They are skipped unless the
deployment URL is supplied, so the default suite stays infrastructure free.

    AIT_E2E_BASE_URL=http://localhost:8080 \
    AIT_E2E_EMAIL=lead@company.local AIT_E2E_PASSWORD='Analyst!2026' \
    pytest tests/e2e -m e2e

Run `docker compose up -d` and `docker compose run --rm seed` first.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx
import pytest

BASE_URL = os.environ.get("AIT_E2E_BASE_URL")
EMAIL = os.environ.get("AIT_E2E_EMAIL", "lead@company.local")
PASSWORD = os.environ.get("AIT_E2E_PASSWORD", "Analyst!2026")
CLIENT_EMAIL = os.environ.get("AIT_E2E_CLIENT_EMAIL", "client@client.local")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not BASE_URL,
                       reason="set AIT_E2E_BASE_URL to run against a live deployment"),
]


@pytest.fixture(scope="module")
def http() -> httpx.Client:
    with httpx.Client(base_url=f"{BASE_URL}/api/v1", timeout=120) as client:
        yield client


def _token(http: httpx.Client, email: str, password: str = PASSWORD) -> str:
    response = http.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["accessToken"]


@pytest.fixture(scope="module")
def auth(http: httpx.Client) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(http, EMAIL)}"}


@pytest.fixture(scope="module")
def project_id(http: httpx.Client, auth: dict[str, str]) -> str:
    response = http.get("/projects", headers=auth)
    assert response.status_code == 200, response.text
    projects = response.json()
    assert projects, "the deployment has no project; run the seed first"
    return projects[0]["projectId"]


def test_service_endpoints_are_healthy() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        health = client.get("/health")
        assert health.status_code == 200

        ready = client.get("/ready")
        assert ready.status_code == 200
        assert ready.json()["database"] == "ok", "the stack reports its database state"


def test_the_web_tier_serves_the_application_and_proxies_the_api() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "<div id=\"root\">" in page.text

        # Client side routing falls back to the application shell.
        deep = client.get("/projects/unknown/backlog")
        assert deep.status_code == 200

        proxied = client.get("/api/v1/auth/providers")
        assert proxied.status_code == 200
        assert "local" in proxied.json()


def test_seeded_portfolio_is_readable(http: httpx.Client, auth: dict[str, str],
                                      project_id: str) -> None:
    response = http.get("/projects", headers=auth)
    project = next(p for p in response.json() if p["projectId"] == project_id)
    assert project["stories"] > 0
    assert project["localOnly"] is True


def test_backlog_was_produced_by_the_analysis(http: httpx.Client, auth: dict[str, str],
                                              project_id: str) -> None:
    tree = http.get(f"/projects/{project_id}/backlog/tree", headers=auth)
    assert tree.status_code == 200
    roots = tree.json()
    assert roots, "the seed runs the analyst workflow and should leave a backlog"
    assert any(node["children"] for node in roots)


def test_approval_cascade_against_the_real_database(http: httpx.Client,
                                                    auth: dict[str, str],
                                                    project_id: str) -> None:
    """Exercises the transactional commit path on a replica set."""
    tree = http.get(f"/projects/{project_id}/backlog/tree", headers=auth).json()
    candidate = next((node for node in tree if node["approvedVersion"] is None), None)
    if candidate is None:
        pytest.skip("every root in this deployment is already approved")

    preview = http.post(f"/projects/{project_id}/approvals/preview/{candidate['id']}",
                        headers=auth)
    assert preview.status_code == 200
    manifest = preview.json()

    waivers = [{"blockerKind": blocker["kind"], "targetId": blocker.get("targetId"),
                "rationale": "Accepted during the automated end to end check"}
               for blocker in manifest["blockers"]
               if blocker["severity"] == "critical" and blocker["waivable"]]

    decision = http.post(f"/projects/{project_id}/approvals/decisions", headers=auth,
                         json={"manifestId": manifest["id"],
                               "manifestHash": manifest["manifestHash"],
                               "decision": "approve", "waivers": waivers})
    assert decision.status_code == 201, decision.text
    event = decision.json()
    assert event["committed"] is True

    replay = http.post(f"/projects/{project_id}/approvals/decisions", headers=auth,
                       json={"manifestId": manifest["id"],
                             "manifestHash": manifest["manifestHash"],
                             "decision": "approve", "waivers": waivers})
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "version_conflict"

    # Leave the deployment as it was found.
    http.post(f"/projects/{project_id}/approvals/events/{event['id']}/revoke",
              headers=auth, json={"reason": "automated end to end check", "itemIds": []})


def test_client_isolation_on_the_live_deployment(http: httpx.Client,
                                                 project_id: str) -> None:
    headers = {"Authorization": f"Bearer {_token(http, CLIENT_EMAIL)}"}
    for url in [f"/projects/{project_id}",
                f"/projects/{project_id}/backlog/tree",
                f"/projects/{project_id}/cost-summary"]:
        assert http.get(url, headers=headers).status_code == 403


def test_charts_and_reports_answer(http: httpx.Client, auth: dict[str, str],
                                   project_id: str) -> None:
    for chart in ["planned_vs_actual", "quality_scope", "cumulative_flow"]:
        response = http.get(f"/projects/{project_id}/charts/{chart}", headers=auth)
        assert response.status_code == 200, chart
        assert response.json()["definition"]

    preview = http.post(f"/projects/{project_id}/reports/preview", headers=auth,
                        json={"dataset": "backlog", "limit": 10})
    assert preview.status_code == 200
    assert preview.json()["snapshotId"]


def test_export_round_trip_through_object_storage(http: httpx.Client,
                                                  auth: dict[str, str],
                                                  project_id: str) -> None:
    started = http.post(f"/projects/{project_id}/exports", headers=auth,
                        json={"dataset": "backlog", "format": "json"})
    assert started.status_code == 202, started.text
    job_id = started.json()["exportJobId"]

    download = http.get(f"/projects/{project_id}/exports/{job_id}/download", headers=auth)
    assert download.status_code == 200
    payload = json.loads(download.content)
    assert payload["schemaVersion"] == "1.0"
    assert payload["projectId"] == project_id


def test_the_worker_picks_up_a_queued_job(http: httpx.Client, auth: dict[str, str],
                                          project_id: str) -> None:
    """An asynchronous export proves the worker process is consuming the queue."""
    started = http.post(f"/projects/{project_id}/exports", headers=auth,
                        params={"async": "true"},
                        json={"dataset": "backlog", "format": "xlsx"})
    assert started.status_code == 202
    job_id = started.json()["jobId"]

    deadline = time.time() + 90
    status: str | None = None
    while time.time() < deadline:
        jobs = http.get(f"/projects/{project_id}/jobs", headers=auth)
        assert jobs.status_code == 200
        row = next((job for job in jobs.json() if job["id"] == job_id), None)
        if row and row["status"] in {"succeeded", "failed"}:
            status = row["status"]
            break
        time.sleep(3)

    assert status == "succeeded", f"worker did not complete the job (status={status})"


def test_audit_trail_is_written_on_the_live_deployment(http: httpx.Client,
                                                       auth: dict[str, str],
                                                       project_id: str) -> None:
    response = http.get(f"/projects/{project_id}/audit", headers=auth,
                        params={"limit": 20})
    assert response.status_code == 200
    assert response.json(), "the seeded run must have left an audit trail"


def test_openapi_document_is_published() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        response = client.get("/api/openapi.json")
        if response.status_code == 404:
            pytest.skip("the API docs are not exposed through the web tier")
        document: dict[str, Any] = response.json()
        assert document["openapi"].startswith("3.")
        assert "/api/v1/projects" in document["paths"]
