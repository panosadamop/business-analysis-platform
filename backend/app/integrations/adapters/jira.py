"""Jira Cloud adapter.

Hierarchy and field availability are discovered from the tenant. Jira does not
guarantee a native level between epic and story, so the feature level is mapped
through a configured issue type or a link strategy, never by silently flattening
the hierarchy.

Reference: https://developer.atlassian.com/cloud/jira/platform/rest/v3/
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any

import httpx

from app.core.utils import utcnow
from app.integrations.base import (ConnectorAdapter, Credential, PublishOutcome,
                                   RemoteItem)
from app.models.integration import (CapabilityReport, FieldRule, FieldOwnership,
                                    TypeMapping)

DOCUMENTED_DEFAULTS = CapabilityReport(
    provider="jira",
    discovered_at=utcnow(),
    hierarchy_levels=["Epic", "Standard issue", "Subtask"],
    supports_worklogs=True,
    supports_webhooks=True,
    limitations=[
        "No credentials are configured, so this report comes from Jira's documented "
        "model rather than from your tenant. Run discovery again after storing "
        "credentials before approving a mapping.",
        "Jira has no guaranteed native level between Epic and Standard issue; the "
        "feature level needs a configured issue type or an explicit link strategy.",
    ],
    suggested_type_mappings=[
        TypeMapping(canonical_type="epic", external_type="Epic", strategy="native"),
        TypeMapping(canonical_type="feature", external_type=None, strategy="link",
                    note="Map to a configured issue type or link child stories to a "
                         "parent issue; do not assume an extra native level."),
        TypeMapping(canonical_type="story", external_type="Story", strategy="native"),
        TypeMapping(canonical_type="task", external_type="Sub-task", strategy="native"),
        TypeMapping(canonical_type="criterion", external_type=None,
                    strategy="description",
                    note="Acceptance criteria go to a mapped field or the description."),
        TypeMapping(canonical_type="test_case", external_type=None, strategy="link",
                    note="Requires a configured test management app or linked artifact."),
    ],
    suggested_field_rules=[
        FieldRule(canonical_field="title", external_field="summary",
                  ownership=FieldOwnership.INTERNAL, direction="outbound"),
        FieldRule(canonical_field="description", external_field="description",
                  ownership=FieldOwnership.INTERNAL, direction="outbound"),
        FieldRule(canonical_field="executionStatus", external_field="status",
                  ownership=FieldOwnership.EXTERNAL, direction="inbound"),
        FieldRule(canonical_field="ownerId", external_field="assignee",
                  ownership=FieldOwnership.EXTERNAL, direction="both"),
        FieldRule(canonical_field="storyPoints", external_field=None,
                  ownership=FieldOwnership.THREE_WAY, direction="both",
                  supported=False,
                  note="Discover the tenant's story point custom field id."),
        FieldRule(canonical_field="acceptanceCriteria", external_field=None,
                  ownership=FieldOwnership.INTERNAL, direction="outbound",
                  supported=False,
                  note="No standard Jira field; configure a custom field or append to "
                       "the description."),
    ],
)


class JiraAdapter(ConnectorAdapter):
    provider = "jira"

    def _client(self) -> httpx.AsyncClient:
        auth = base64.b64encode(
            f"{self.credential.email}:{self.credential.token}".encode()).decode()
        return httpx.AsyncClient(
            base_url=(self.credential.base_url or "").rstrip("/"),
            headers={"Authorization": f"Basic {auth}", "Accept": "application/json",
                     "Content-Type": "application/json"},
            timeout=30)

    async def discover(self) -> CapabilityReport:
        if not self.configured:
            report = DOCUMENTED_DEFAULTS.model_copy(deep=True)
            report.discovered_at = utcnow()
            return report

        report = CapabilityReport(provider="jira", discovered_at=utcnow(),
                                  supports_worklogs=True, supports_webhooks=True)
        async with self._client() as client:
            projects = await client.get("/rest/api/3/project/search", params={"maxResults": 50})
            if projects.status_code == 200:
                report.projects = [
                    {"key": p["key"], "name": p["name"], "id": p["id"]}
                    for p in projects.json().get("values", [])
                ]
            types = await client.get("/rest/api/3/issuetype")
            if types.status_code == 200:
                report.item_types = [
                    {"id": t["id"], "name": t["name"], "subtask": t.get("subtask", False),
                     "hierarchyLevel": t.get("hierarchyLevel")}
                    for t in types.json()
                ]
                report.hierarchy_levels = sorted(
                    {str(t.get("hierarchyLevel")) for t in types.json()})
            fields = await client.get("/rest/api/3/field")
            if fields.status_code == 200:
                report.fields = [
                    {"id": f["id"], "name": f["name"], "custom": f.get("custom", False),
                     "schema": f.get("schema", {})}
                    for f in fields.json()
                ]
            users = await client.get("/rest/api/3/users/search", params={"maxResults": 50})
            if users.status_code == 200:
                report.identities = [
                    {"accountId": u.get("accountId"), "displayName": u.get("displayName"),
                     "email": u.get("emailAddress")}
                    for u in users.json()
                ]

        point_fields = [f for f in report.fields
                        if "point" in f["name"].lower() or "estimate" in f["name"].lower()]
        report.suggested_field_rules = list(DOCUMENTED_DEFAULTS.suggested_field_rules)
        if point_fields:
            for rule in report.suggested_field_rules:
                if rule.canonical_field == "storyPoints":
                    rule.external_field = point_fields[0]["id"]
                    rule.supported = True
                    rule.note = f"Discovered field '{point_fields[0]['name']}'"
        names = {t["name"] for t in report.item_types}
        report.suggested_type_mappings = [
            TypeMapping(canonical_type="epic",
                        external_type="Epic" if "Epic" in names else None,
                        strategy="native" if "Epic" in names else "unsupported"),
            TypeMapping(canonical_type="feature", external_type=None, strategy="link",
                        note="No guaranteed native feature level; configure a type or link."),
            TypeMapping(canonical_type="story",
                        external_type="Story" if "Story" in names else
                        ("Task" if "Task" in names else None),
                        strategy="native"),
            TypeMapping(canonical_type="task",
                        external_type="Sub-task" if "Sub-task" in names else None,
                        strategy="native" if "Sub-task" in names else "unsupported"),
        ]
        if "Epic" not in names:
            report.limitations.append("This tenant exposes no Epic issue type; the epic "
                                      "level needs an explicit fallback mapping.")
        return report

    async def publish(self, item: dict[str, Any], *, type_mapping: TypeMapping,
                      field_rules: list[FieldRule],
                      external_id: str | None) -> PublishOutcome:
        if not self.configured:
            return PublishOutcome(internal_id=item["id"], status="failed",
                                  message="No Jira credentials are configured")
        if type_mapping.strategy == "unsupported" or not type_mapping.external_type:
            return PublishOutcome(
                internal_id=item["id"], status="skipped",
                message=f"No Jira issue type is mapped for {type_mapping.canonical_type}; "
                        "the item stays in the internal model")

        fields: dict[str, Any] = {
            "project": {"key": self.credential.project},
            "issuetype": {"name": type_mapping.external_type},
        }
        unsupported_fields: list[str] = []
        for rule in field_rules:
            if rule.direction == "inbound" or not rule.supported or not rule.external_field:
                if rule.canonical_field in item and rule.direction != "inbound":
                    unsupported_fields.append(rule.canonical_field)
                continue
            value = item.get(rule.canonical_field)
            if value is None:
                continue
            if rule.external_field == "description":
                fields["description"] = _adf(str(value))
            else:
                fields[rule.external_field] = value

        async with self._client() as client:
            if external_id:
                response = await client.put(f"/rest/api/3/issue/{external_id}",
                                            json={"fields": fields})
                if response.status_code in (200, 204):
                    return PublishOutcome(internal_id=item["id"], status="updated",
                                          external_id=external_id,
                                          unsupported_fields=unsupported_fields)
                return PublishOutcome(internal_id=item["id"], status="failed",
                                      message=response.text[:400])
            response = await client.post("/rest/api/3/issue", json={"fields": fields})
            if response.status_code in (200, 201):
                data = response.json()
                return PublishOutcome(
                    internal_id=item["id"], status="created", external_id=data["id"],
                    external_key=data.get("key"),
                    url=f"{self.credential.base_url}/browse/{data.get('key')}",
                    unsupported_fields=unsupported_fields)
            return PublishOutcome(internal_id=item["id"], status="failed",
                                  message=response.text[:400])

    async def fetch_changes(self, since: str | None) -> list[RemoteItem]:
        if not self.configured:
            return []
        jql = f"project = {self.credential.project}"
        if since:
            jql += f" AND updated >= '{since}'"
        async with self._client() as client:
            response = await client.post("/rest/api/3/search",
                                         json={"jql": jql, "maxResults": 100,
                                               "fields": ["summary", "status", "assignee",
                                                          "updated", "timetracking"]})
            if response.status_code != 200:
                return []
            return [
                RemoteItem(external_id=issue["id"], external_key=issue.get("key"),
                           url=f"{self.credential.base_url}/browse/{issue.get('key')}",
                           fields=issue.get("fields", {}),
                           revision=issue.get("fields", {}).get("updated"))
                for issue in response.json().get("issues", [])
            ]

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        secret = (self.credential.token or "").encode()
        signature = headers.get("x-hub-signature") or headers.get("X-Hub-Signature")
        if not secret or not signature:
            return False
        expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)


def _adf(text: str) -> dict[str, Any]:
    """Jira Cloud expects Atlassian Document Format for rich text fields."""
    return {
        "type": "doc", "version": 1,
        "content": [{"type": "paragraph",
                     "content": [{"type": "text", "text": paragraph}]}
                    for paragraph in text.split("\n\n") if paragraph.strip()],
    }
