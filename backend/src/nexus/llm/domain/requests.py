"""Provider-independent LLM request contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from nexus.llm.domain.messages import LLMMessage
from nexus.llm.domain.tools import LLMToolDefinition


@dataclass(frozen=True)
class LLMRequest:
    model: str
    messages: Sequence[LLMMessage]
    temperature: float | None = None
    max_output_tokens: int | None = None
    tools: Sequence[LLMToolDefinition] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("LLM model must not be empty")
        if not self.messages:
            raise ValueError("LLM request must include at least one message")
        if self.temperature is not None and self.temperature < 0:
            raise ValueError("LLM temperature must not be negative")
        if self.max_output_tokens is not None and self.max_output_tokens <= 0:
            raise ValueError("LLM max output tokens must be positive")
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "tools", tuple(self.tools))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
