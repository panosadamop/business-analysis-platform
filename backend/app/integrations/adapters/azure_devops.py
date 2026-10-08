"""Azure DevOps Boards adapter.

Work item types depend on the project process: Agile exposes User Story, Scrum
exposes Product Backlog Item, CMMI exposes Requirement. The actual types are
discovered rather than assumed.

Reference:
https://learn.microsoft.com/en-us/azure/devops/boards/work-items/about-work-items
"""
from __future__ import annotations

import base64
from typing import Any

import httpx

from app.core.utils import utcnow
from app.integrations.base import (ConnectorAdapter, PublishOutcome, RemoteItem)
from app.models.integration import (CapabilityReport, FieldOwnership, FieldRule,
                                    TypeMapping)

API_VERSION = "7.1"

DOCUMENTED_DEFAULTS = CapabilityReport(
    provider="azure_devops",
    discovered_at=utcnow(),
    hierarchy_levels=["Epic", "Feature", "User Story / Product Backlog Item", "Task"],
    supports_worklogs=True,
    supports_webhooks=True,
    limitations=[
        "No credentials are configured, so this report comes from the documented "
        "Azure Boards process templates rather than from your organisation.",
        "The story level type depends on the project process: User Story for Agile, "
        "Product Backlog Item for Scrum, Requirement for CMMI. Discover it before "
        "approving the mapping.",
    ],
    suggested_type_mappings=[
        TypeMapping(canonical_type="epic", external_type="Epic", strategy="native"),
        TypeMapping(canonical_type="feature", external_type="Feature", strategy="native"),
        TypeMapping(canonical_type="story", external_type="User Story", strategy="native",
                    note="Discover the actual process specific type."),
        TypeMapping(canonical_type="task", external_type="Task", strategy="native"),
        TypeMapping(canonical_type="criterion", external_type=None, strategy="native",
                    note="Microsoft.VSTS.Common.AcceptanceCriteria where present."),
        TypeMapping(canonical_type="test_case", external_type="Test Case",
                    strategy="link", note="Requires Azure Test Plans."),
    ],
    suggested_field_rules=[
        FieldRule(canonical_field="title", external_field="System.Title",
                  ownership=FieldOwnership.INTERNAL, direction="outbound"),
        FieldRule(canonical_field="description", external_field="System.Description",
                  ownership=FieldOwnership.INTERNAL, direction="outbound"),
        FieldRule(canonical_field="acceptanceCriteria",
                  external_field="Microsoft.VSTS.Common.AcceptanceCriteria",
                  ownership=FieldOwnership.INTERNAL, direction="outbound"),
        FieldRule(canonical_field="storyPoints",
                  external_field="Microsoft.VSTS.Scheduling.StoryPoints",
                  ownership=FieldOwnership.THREE_WAY, direction="both"),
        FieldRule(canonical_field="effortHours",
                  external_field="Microsoft.VSTS.Scheduling.OriginalEstimate",
                  ownership=FieldOwnership.THREE_WAY, direction="both"),
        FieldRule(canonical_field="executionStatus", external_field="System.State",
                  ownership=FieldOwnership.EXTERNAL, direction="inbound"),
        FieldRule(canonical_field="ownerId", external_field="System.AssignedTo",
                  ownership=FieldOwnership.EXTERNAL, direction="both"),
    ],
)


class AzureDevOpsAdapter(ConnectorAdapter):
    provider = "azure_devops"

    def _client(self) -> httpx.AsyncClient:
        auth = base64.b64encode(f":{self.credential.token}".encode()).decode()
        base = (self.credential.base_url
                or f"https://dev.azure.com/{self.credential.organization}")
        return httpx.AsyncClient(base_url=base.rstrip("/"),
                                 headers={"Authorization": f"Basic {auth}",
                                          "Accept": "application/json"},
                                 timeout=30)

    async def discover(self) -> CapabilityReport:
        if not self.configured:
            report = DOCUMENTED_DEFAULTS.model_copy(deep=True)
            report.discovered_at = utcnow()
            return report

        report = CapabilityReport(provider="azure_devops", discovered_at=utcnow(),
                                  supports_worklogs=True, supports_webhooks=True)
        async with self._client() as client:
            projects = await client.get("/_apis/projects",
                                        params={"api-version": API_VERSION})
            if projects.status_code == 200:
                report.projects = [{"id": p["id"], "name": p["name"]}
                                   for p in projects.json().get("value", [])]
            project = self.credential.project
            if project:
                types = await client.get(f"/{project}/_apis/wit/workitemtypes",
                                         params={"api-version": API_VERSION})
                if types.status_code == 200:
                    report.item_types = [{"name": t["name"],
                                          "referenceName": t.get("referenceName")}
                                         for t in types.json().get("value", [])]
                fields = await client.get(f"/{project}/_apis/wit/fields",
                                          params={"api-version": API_VERSION})
                if fields.status_code == 200:
                    report.fields = [{"referenceName": f["referenceName"],
                                      "name": f["name"], "type": f.get("type")}
                                     for f in fields.json().get("value", [])]

        names = {t["name"] for t in report.item_types}
        story_type = next((n for n in ("User Story", "Product Backlog Item", "Requirement")
                           if n in names), None)
        report.suggested_type_mappings = [
            TypeMapping(canonical_type="epic",
                        external_type="Epic" if "Epic" in names else None,
                        strategy="native" if "Epic" in names else "unsupported"),
            TypeMapping(canonical_type="feature",
                        external_type="Feature" if "Feature" in names else None,
                        strategy="native" if "Feature" in names else "link"),
            TypeMapping(canonical_type="story", external_type=story_type,
                        strategy="native" if story_type else "unsupported",
                        note=f"Discovered process type: {story_type}"),
            TypeMapping(canonical_type="task",
                        external_type="Task" if "Task" in names else None,
                        strategy="native" if "Task" in names else "unsupported"),
        ]
        report.suggested_field_rules = list(DOCUMENTED_DEFAULTS.suggested_field_rules)
        available = {f["referenceName"] for f in report.fields}
        for rule in report.suggested_field_rules:
            if rule.external_field and available and rule.external_field not in available:
                rule.supported = False
                rule.note = "Not present in this project process"
        return report

    async def publish(self, item: dict[str, Any], *, type_mapping: TypeMapping,
                      field_rules: list[FieldRule],
                      external_id: str | None) -> PublishOutcome:
        if not self.configured:
            return PublishOutcome(internal_id=item["id"], status="failed",
                                  message="No Azure DevOps credentials are configured")
        if not type_mapping.external_type or type_mapping.strategy == "unsupported":
            return PublishOutcome(internal_id=item["id"], status="skipped",
                                  message="No work item type is mapped for "
                                          f"{type_mapping.canonical_type}")
        operations: list[dict[str, Any]] = []
        unsupported_fields: list[str] = []
        for rule in field_rules:
            if rule.direction == "inbound":
                continue
            if not rule.supported or not rule.external_field:
                if rule.canonical_field in item:
                    unsupported_fields.append(rule.canonical_field)
                continue
            value = item.get(rule.canonical_field)
            if value is None:
                continue
            operations.append({"op": "add", "path": f"/fields/{rule.external_field}",
                               "value": value})

        project = self.credential.project
        async with self._client() as client:
            client.headers["Content-Type"] = "application/json-patch+json"
            if external_id:
                response = await client.patch(
                    f"/{project}/_apis/wit/workitems/{external_id}",
                    params={"api-version": API_VERSION}, json=operations)
                status = "updated"
            else:
                response = await client.post(
                    f"/{project}/_apis/wit/workitems/${type_mapping.external_type}",
                    params={"api-version": API_VERSION}, json=operations)
                status = "created"
            if response.status_code in (200, 201):
                data = response.json()
                return PublishOutcome(internal_id=item["id"], status=status,
                                      external_id=str(data["id"]),
                                      url=data.get("_links", {}).get("html", {}).get("href"),
                                      unsupported_fields=unsupported_fields)
            return PublishOutcome(internal_id=item["id"], status="failed",
                                  message=response.text[:400])

    async def fetch_changes(self, since: str | None) -> list[RemoteItem]:
        if not self.configured:
            return []
        project = self.credential.project
        wiql = ("SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project"
                + (f" AND [System.ChangedDate] >= '{since}'" if since else ""))
        async with self._client() as client:
            query = await client.post(f"/{project}/_apis/wit/wiql",
                                      params={"api-version": API_VERSION},
                                      json={"query": wiql})
            if query.status_code != 200:
                return []
            ids = [str(w["id"]) for w in query.json().get("workItems", [])][:200]
            if not ids:
                return []
            detail = await client.get(f"/{project}/_apis/wit/workitems",
                                      params={"ids": ",".join(ids),
                                              "api-version": API_VERSION})
            if detail.status_code != 200:
                return []
            return [RemoteItem(external_id=str(w["id"]), fields=w.get("fields", {}),
                               revision=str(w.get("rev")))
                    for w in detail.json().get("value", [])]
