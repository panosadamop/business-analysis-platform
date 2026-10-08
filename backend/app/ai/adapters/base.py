"""Model adapter contract.

Adapters are interchangeable per role with capability metadata, health checks
and budgets (section 8.3). An adapter never decides policy; the egress gate does.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelCapabilities:
    name: str
    deployment: str  # local | cloud
    context_tokens: int = 8192
    supports_json_schema: bool = False
    languages: list[str] = field(default_factory=lambda: ["en", "el"])
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0


@dataclass
class AdapterRequest:
    role: str
    language: str
    system_prompt: str
    instruction: str
    context: str
    schema: dict[str, Any]
    temperature: float = 0.0
    max_tokens: int = 4096


@dataclass
class AdapterResponse:
    payload: dict[str, Any]
    model_id: str
    deployment: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    raw: str | None = None
    warnings: list[str] = field(default_factory=list)


class ModelAdapter(ABC):
    """A model that can produce a schema valid role output."""

    deployment: str = "local"

    @property
    @abstractmethod
    def capabilities(self) -> ModelCapabilities: ...

    @abstractmethod
    async def health(self) -> tuple[bool, str]: ...

    @abstractmethod
    async def generate(self, request: AdapterRequest) -> AdapterResponse: ...


class AdapterUnavailable(RuntimeError):
    """The configured model could not be reached.

    A local only job fails or pauses visibly (AT-06); it never falls back to
    cloud.
    """
