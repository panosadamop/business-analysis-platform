"""Asana adapter.

Asana has tasks and subtasks rather than an epic / feature / story hierarchy, so
the canonical levels are carried through configured custom fields and metadata.
This is an implementation mapping, not a claim of an equivalent native hierarchy.

Reference: https://developers.asana.com/docs/webhooks-guide
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Any

import httpx

from app.core.utils import utcnow
from app.integrations.base import ConnectorAdapter, PublishOutcome, RemoteItem
from app.models.integration import (CapabilityReport, FieldOwnership, FieldRule,
                                    TypeMapping)

DOCUMENTED_DEFAULTS = CapabilityReport(
    provider="asana",
    discovered_at=utcnow(),
    hierarchy_levels=["Project", "Task", "Subtask"],
    supports_worklogs=False,
    supports_webhooks=True,
    limitations=[
        "No credentials are configured, so this report comes from Asana's documented "
        "model rather than from your workspace.",
        "Asana has no native epic / feature / story hierarchy. Canonical levels are "
        "carried in a custom field or in structured task metadata.",
        "Asana has no native worklog concept; actual effort cannot be synchronised "
        "unless a custom field is configured for it.",
    ],
    suggested_type_mappings=[
        TypeMapping(canonical_type="epic", external_type="Task", strategy="metadata",
                    note="Container task carrying canonical type metadata."),
        TypeMapping(canonical_type="feature", external_type="Task", strategy="metadata",
                    note="Task or linked grouping with canonical type metadata."),
        TypeMapping(canonical_type="story", external_type="Subtask", strategy="metadata"),
        TypeMapping(canonical_type="task", external_type="Subtask", strategy="metadata"),
        TypeMapping(canonical_type="criterion", external_type=None,
                    strategy="description",
                    note="Structured description section or a permitted custom field."),
        TypeMapping(canonical_type="test_case", external_type=None, strategy="link"),
    ],
    suggested_field_rules=[
        FieldRule(canonical_field="title", external_field="name",
                  ownership=FieldOwnership.INTERNAL, direction="outbound"),
        FieldRule(canonical_field="description", external_field="notes",
                  ownership=FieldOwnership.INTERNAL, direction="outbound"),
        FieldRule(canonical_field="executionStatus", external_field="completed",
                  ownership=FieldOwnership.EXTERNAL, direction="inbound"),
        FieldRule(canonical_field="ownerId", external_field="assignee",
                  ownership=FieldOwnership.EXTERNAL, direction="both"),
        FieldRule(canonical_field="storyPoints", external_field=None,
                  ownership=FieldOwnership.THREE_WAY, direction="both", supported=False,
                  note="Needs a permitted numeric custom field."),
        FieldRule(canonical_field="effortHours", external_field=None,
                  ownership=FieldOwnership.IGNORE, direction="outbound", supported=False,
                  note="No native effort field."),
    ],
)


class AsanaAdapter(ConnectorAdapter):
    provider = "asana"

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url="https://app.asana.com/api/1.0",
            headers={"Authorization": f"Bearer {self.credential.token}",
                     "Accept": "application/json"},
            timeout=30)

    async def discover(self) -> CapabilityReport:
        if not self.configured:
            report = DOCUMENTED_DEFAULTS.model_copy(deep=True)
            report.discovered_at = utcnow()
            return report

        report = CapabilityReport(provider="asana", discovered_at=utcnow(),
                                  supports_worklogs=False, supports_webhooks=True,
                                  hierarchy_levels=["Project", "Task", "Subtask"])
        async with self._client() as client:
            projects = await client.get("/projects", params={"limit": 100})
            if projects.status_code == 200:
                report.projects = [{"gid": p["gid"], "name": p["name"]}
                                   for p in projects.json().get("data", [])]
            if self.credential.project:
                fields = await client.get(
                    f"/projects/{self.credential.project}/custom_field_settings")
                if fields.status_code == 200:
                    report.fields = [
                        {"gid": f.get("custom_field", {}).get("gid"),
                         "name": f.get("custom_field", {}).get("name"),
                         "type": f.get("custom_field", {}).get("type")}
                        for f in fields.json().get("data", [])
                    ]
            users = await client.get("/users", params={"limit": 50})
            if users.status_code == 200:
                report.identities = [{"gid": u["gid"], "name": u.get("name")}
                                     for u in users.json().get("data", [])]

        report.suggested_type_mappings = list(DOCUMENTED_DEFAULTS.suggested_type_mappings)
        report.suggested_field_rules = list(DOCUMENTED_DEFAULTS.suggested_field_rules)
        numeric = [f for f in report.fields if f.get("type") == "number"]
        if numeric:
            for rule in report.suggested_field_rules:
                if rule.canonical_field == "storyPoints":
                    rule.external_field = numeric[0]["gid"]
                    rule.supported = True
                    rule.note = f"Discovered custom field '{numeric[0]['name']}'"
        report.limitations = [
            "Asana has no native epic / feature / story hierarchy; canonical levels are "
            "carried as metadata and the hierarchy is reconstructed internally.",
        ]
        if not numeric:
            report.limitations.append(
                "No numeric custom field is available for story points; the value stays "
                "in the internal model only.")
        return report

    async def publish(self, item: dict[str, Any], *, type_mapping: TypeMapping,
                      field_rules: list[FieldRule],
                      external_id: str | None) -> PublishOutcome:
        if not self.configured:
            return PublishOutcome(internal_id=item["id"], status="failed",
                                  message="No Asana credentials are configured")
        data: dict[str, Any] = {}
        custom_fields: dict[str, Any] = {}
        unsupported_fields: list[str] = []
        for rule in field_rules:
            if rule.direction == "inbound":
                continue
            value = item.get(rule.canonical_field)
            if not rule.supported or not rule.external_field:
                if value is not None:
                    unsupported_fields.append(rule.canonical_field)
                continue
            if value is None:
                continue
            if rule.external_field in {"name", "notes", "assignee", "completed"}:
                data[rule.external_field] = value
            else:
                custom_fields[rule.external_field] = value

        # Canonical type travels as structured metadata appended to the notes.
        notes = data.get("notes", "")
        data["notes"] = (f"{notes}\n\n---\nCanonical type: {type_mapping.canonical_type}\n"
                         f"Internal id: {item.get('stableId', item['id'])}").strip()
        if custom_fields:
            data["custom_fields"] = custom_fields
        if not external_id:
            data["projects"] = [self.credential.project]

        async with self._client() as client:
            if external_id:
                response = await client.put(f"/tasks/{external_id}", json={"data": data})
                status = "updated"
            else:
                response = await client.post("/tasks", json={"data": data})
                status = "created"
            if response.status_code in (200, 201):
                payload = response.json().get("data", {})
                return PublishOutcome(
                    internal_id=item["id"], status=status, external_id=payload.get("gid"),
                    url=payload.get("permalink_url"),
                    unsupported_fields=unsupported_fields)
            return PublishOutcome(internal_id=item["id"], status="failed",
                                  message=response.text[:400])

    async def fetch_changes(self, since: str | None) -> list[RemoteItem]:
        if not self.configured or not self.credential.project:
            return []
        params: dict[str, Any] = {"limit": 100,
                                  "opt_fields": "name,notes,completed,assignee,modified_at"}
        if since:
            params["modified_since"] = since
        async with self._client() as client:
            response = await client.get(f"/projects/{self.credential.project}/tasks",
                                        params=params)
            if response.status_code != 200:
                return []
            return [RemoteItem(external_id=task["gid"], fields=task,
                               revision=task.get("modified_at"))
                    for task in response.json().get("data", [])]

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        secret = (self.credential.token or "").encode()
        signature = headers.get("x-hook-signature") or headers.get("X-Hook-Signature")
        if not secret or not signature:
            return False
        expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
