"""AI gateway: routing, egress policy, budgets and health (section 17.1).

The gateway is the only path from project content to a model. It decides local
versus cloud from project policy, prepares the payload through the egress gate
and validates the response against the role schema before anything is returned.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.ai import egress, prompts, schemas
from app.ai.adapters.base import (AdapterRequest, AdapterResponse,
                                  AdapterUnavailable, ModelAdapter)
from app.ai.adapters.cloud import default_cloud_adapter
from app.ai.adapters.local import default_local_adapter
from app.core.config import settings
from app.core.errors import PolicyBlocked
from app.models.analysis import ModelUsage
from app.models.common import Money
from app.models.project import Project

log = logging.getLogger(__name__)


@dataclass
class GatewayResult:
    payload: dict[str, Any]
    validated: Any
    usage: ModelUsage
    warnings: list[str]


class BudgetExceeded(RuntimeError):
    pass


def _adapter_for(project: Project, role: str) -> tuple[ModelAdapter, str]:
    """Pick the adapter for a role. Cloud is opt in, per project and per role."""
    policy = project.ai_policy
    wants_cloud = (
        settings.cloud_enabled_globally
        and policy.cloud_enabled
        and not policy.local_only
        and (not policy.allow_cloud_for_roles or role in policy.allow_cloud_for_roles)
    )
    if wants_cloud:
        cloud = default_cloud_adapter()
        if cloud is not None:
            return cloud, "cloud"
        # No cloud fallback is invented; the local model is used and the caller
        # is told why.
        log.info("cloud requested but no provider is configured, using local")
    return default_local_adapter(), "local"


def _cost(adapter: ModelAdapter, response: AdapterResponse) -> Money:
    caps = adapter.capabilities
    total = (Decimal(str(response.prompt_tokens)) / 1000 * Decimal(str(caps.cost_per_1k_input))
             + Decimal(str(response.completion_tokens)) / 1000
             * Decimal(str(caps.cost_per_1k_output)))
    return Money.of(total, "EUR")


def format_context(chunks: list[Any], *, limit_chars: int = 120_000) -> str:
    """Render evidence chunks with their locators so the model can cite them."""
    parts: list[str] = []
    used = 0
    for chunk in chunks:
        text = egress.strip_injected_instructions(chunk.text)
        block = (f"<<CHUNK src={chunk.source_version_id} kind={chunk.locator_kind} "
                 f"loc={chunk.locator_value}>>\n{text}")
        if used + len(block) > limit_chars:
            break
        parts.append(block)
        used += len(block)
    return "\n".join(parts)


async def run_role(project: Project, role: str, *, chunks: list[Any],
                   backlog_json: str = "[]", actor_id: str | None = None,
                   language: str | None = None) -> GatewayResult:
    """Execute one analyst role and return validated, schema conformant output."""
    adapter, target = _adapter_for(project, role)
    model_id = adapter.capabilities.name
    output_language = language or str(project.output_language)

    healthy, detail = await adapter.health()
    if not healthy:
        raise AdapterUnavailable(
            f"The configured {target} model '{model_id}' is not available: {detail}. "
            "The job is paused; no project content was sent anywhere else.")

    classified = [(str(getattr(c, "classification", "confidential")), c.text) for c in chunks]
    try:
        prepared = await egress.prepare(
            project, target=target, role=role, model_id=model_id,
            chunks=classified,
            categories=["evidence_excerpt", "requirement_text", "project_metadata"],
            actor_id=actor_id)
    except egress.EgressDenied as denied:
        raise PolicyBlocked(str(denied.reason),
                            details={"role": role, "target": target,
                                     "modelId": model_id}) from denied

    warnings: list[str] = []
    if target == "cloud" and prepared.redactions:
        warnings.append(
            "Sanitisation removed " +
            ", ".join(f"{count} {kind}" for kind, count in prepared.redactions.items()) +
            ". Sanitisation reduces disclosure; it is not a guarantee of anonymisation.")
    if len(prepared.text) < sum(len(t) for _, t in classified):
        warnings.append("Some evidence was withheld from this model by project policy.")

    # Build the context from the permitted, sanitised text while keeping the
    # locator markers the adapter needs for citations.
    permitted_classifications = egress.allowed_classifications(project, target=target)
    permitted_chunks = [c for c in chunks
                        if str(getattr(c, "classification", "confidential"))
                        in permitted_classifications]
    context = format_context(permitted_chunks)
    if target == "cloud" and project.ai_policy.sanitize_payloads:
        context, _ = egress.sanitize(context)

    request = AdapterRequest(
        role=role,
        language=output_language,
        system_prompt=prompts.system_prompt(role, output_language),
        instruction=prompts.instruction(role, backlog_json=backlog_json),
        context=context,
        schema=schemas.json_schema(role),
    )
    response = await adapter.generate(request)

    try:
        validated = schemas.validate(role, response.payload)
    except schemas.ValidationError as exc:
        raise AdapterUnavailable(
            f"The {role} output did not satisfy the versioned schema and was discarded: "
            f"{exc.error_count()} validation error(s)") from exc

    usage = ModelUsage(
        role=role, model_id=model_id, deployment=target,
        prompt_template_version=prompts.PROMPT_TEMPLATE_VERSION,
        prompt_tokens=response.prompt_tokens, completion_tokens=response.completion_tokens,
        cost=_cost(adapter, response), latency_ms=response.latency_ms,
    )
    return GatewayResult(payload=response.payload, validated=validated, usage=usage,
                         warnings=warnings + response.warnings)


async def health_report(project: Project | None = None) -> list[dict[str, Any]]:
    report: list[dict[str, Any]] = []
    local = default_local_adapter()
    healthy, detail = await local.health()
    report.append({"deployment": "local", "modelId": local.capabilities.name,
                   "healthy": healthy, "detail": detail,
                   "contextTokens": local.capabilities.context_tokens})
    cloud = default_cloud_adapter()
    if cloud is not None:
        healthy, detail = await cloud.health()
        report.append({"deployment": "cloud", "modelId": cloud.capabilities.name,
                       "healthy": healthy, "detail": detail,
                       "enabledGlobally": settings.cloud_enabled_globally})
    else:
        report.append({"deployment": "cloud", "modelId": None, "healthy": False,
                       "detail": "No cloud provider is configured",
                       "enabledGlobally": settings.cloud_enabled_globally})
    if project is not None:
        report.append({
            "deployment": "policy",
            "localOnly": project.ai_policy.local_only,
            "cloudEnabled": project.ai_policy.cloud_enabled,
            "maxCloudClassification": str(project.ai_policy.max_cloud_classification),
            "detail": ("Cloud payloads are blocked for this project"
                       if project.ai_policy.local_only else
                       "Only permitted, minimised and sanitised context may leave"),
        })
    return report
