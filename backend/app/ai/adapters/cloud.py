"""Cloud model adapters.

A cloud adapter is only ever reached through the egress gate. Provider
retention and training settings, network destinations and contracts must be
validated during implementation; this module does not assert that every
provider supports identical privacy controls.
"""
from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.ai.adapters.base import (AdapterRequest, AdapterResponse,
                                  AdapterUnavailable, ModelAdapter,
                                  ModelCapabilities)
from app.core.config import settings


class AnthropicAdapter(ModelAdapter):
    deployment = "cloud"

    def __init__(self, api_key: str, model_id: str) -> None:
        self.api_key = api_key
        self.model_id = model_id

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(name=self.model_id, deployment="cloud",
                                 context_tokens=200_000, supports_json_schema=True,
                                 cost_per_1k_input=0.003, cost_per_1k_output=0.015)

    async def health(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "No API key configured"
        return True, "Credentials present; connectivity is verified per request"

    async def generate(self, request: AdapterRequest) -> AdapterResponse:
        started = time.perf_counter()
        body: dict[str, Any] = {
            "model": self.model_id,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "system": request.system_prompt,
            "messages": [{
                "role": "user",
                "content": (f"{request.instruction}\n\n{request.context}\n\n"
                            "Reply with a single JSON object matching this schema:\n"
                            f"{json.dumps(request.schema)[:6000]}"),
            }],
        }
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": self.api_key,
                             "anthropic-version": "2023-06-01",
                             "content-type": "application/json"},
                    json=body)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            raise AdapterUnavailable(f"The cloud provider is unreachable: {exc}") from exc

        text = "".join(block.get("text", "") for block in data.get("content", []))
        payload = _parse_json_object(text)
        usage = data.get("usage", {})
        return AdapterResponse(
            payload=payload, model_id=self.model_id, deployment="cloud",
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
            latency_ms=int((time.perf_counter() - started) * 1000), raw=text,
        )


class OpenAICompatibleCloudAdapter(ModelAdapter):
    deployment = "cloud"

    def __init__(self, api_key: str, model_id: str,
                 base_url: str = "https://api.openai.com/v1") -> None:
        self.api_key = api_key
        self.model_id = model_id
        self.base_url = base_url.rstrip("/")

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(name=self.model_id, deployment="cloud",
                                 context_tokens=128_000, supports_json_schema=True)

    async def health(self) -> tuple[bool, str]:
        return bool(self.api_key), "Credentials present" if self.api_key else "No API key"

    async def generate(self, request: AdapterRequest) -> AdapterResponse:
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model_id,
                        "temperature": request.temperature,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": request.system_prompt},
                            {"role": "user",
                             "content": f"{request.instruction}\n\n{request.context}"},
                        ],
                    })
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            raise AdapterUnavailable(f"The cloud provider is unreachable: {exc}") from exc
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return AdapterResponse(
            payload=_parse_json_object(content), model_id=self.model_id,
            deployment="cloud", prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_ms=int((time.perf_counter() - started) * 1000), raw=content,
        )


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        text = text[4:] if text.startswith("json") else text
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise AdapterUnavailable("The model response contained no JSON object")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise AdapterUnavailable(f"The model response was not valid JSON: {exc}") from exc


def default_cloud_adapter() -> ModelAdapter | None:
    if settings.cloud_provider == "anthropic" and settings.cloud_api_key:
        return AnthropicAdapter(settings.cloud_api_key, settings.cloud_model)
    if settings.cloud_provider == "openai" and settings.cloud_api_key:
        return OpenAICompatibleCloudAdapter(settings.cloud_api_key, settings.cloud_model)
    return None
