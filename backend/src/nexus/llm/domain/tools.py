"""Provider-independent LLM tool proposal contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class LLMToolDefinition:
    name: str
    description: str
    parameters_schema: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("LLM tool name must not be empty")
        if not self.description:
            raise ValueError("LLM tool description must not be empty")
        object.__setattr__(
            self,
            "parameters_schema",
            MappingProxyType(dict(self.parameters_schema)),
        )


@dataclass(frozen=True)
class LLMToolCall:
    id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("LLM tool call ID must not be empty")
        if not self.name:
            raise ValueError("LLM tool call name must not be empty")
        object.__setattr__(self, "arguments", MappingProxyType(dict(self.arguments)))
