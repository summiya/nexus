"""Provider-independent LLM response contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from nexus.llm.domain.messages import LLMMessage
from nexus.llm.domain.tools import LLMToolCall
from nexus.llm.domain.usage import LLMUsage


class LLMFinishReason(StrEnum):
    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LLMResponse:
    message: LLMMessage
    finish_reason: LLMFinishReason = LLMFinishReason.UNKNOWN
    usage: LLMUsage | None = None
    tool_calls: Sequence[LLMToolCall] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        if self.message.content is None and not self.tool_calls:
            raise ValueError(
                "LLM responses without message content must include tool calls"
            )
