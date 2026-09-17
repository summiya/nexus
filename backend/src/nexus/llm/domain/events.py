"""Provider-independent LLM streaming event contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from nexus.llm.domain.errors import LLMErrorKind
from nexus.llm.domain.responses import LLMFinishReason
from nexus.llm.domain.tools import LLMToolCall
from nexus.llm.domain.usage import LLMUsage


class LLMEventType(StrEnum):
    STARTED = "started"
    TEXT_DELTA = "text_delta"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_DELTA = "tool_call_delta"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    USAGE = "usage"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass(frozen=True)
class LLMStartedEvent:
    type: LLMEventType = LLMEventType.STARTED
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class LLMTextDeltaEvent:
    delta: str
    type: LLMEventType = LLMEventType.TEXT_DELTA


@dataclass(frozen=True)
class LLMToolCallStartedEvent:
    tool_call_id: str
    name: str
    type: LLMEventType = LLMEventType.TOOL_CALL_STARTED


@dataclass(frozen=True)
class LLMToolCallDeltaEvent:
    tool_call_id: str
    arguments_delta: str
    type: LLMEventType = LLMEventType.TOOL_CALL_DELTA


@dataclass(frozen=True)
class LLMToolCallCompletedEvent:
    tool_call: LLMToolCall
    type: LLMEventType = LLMEventType.TOOL_CALL_COMPLETED


@dataclass(frozen=True)
class LLMUsageEvent:
    usage: LLMUsage
    type: LLMEventType = LLMEventType.USAGE


@dataclass(frozen=True)
class LLMCompletedEvent:
    finish_reason: LLMFinishReason = LLMFinishReason.UNKNOWN
    type: LLMEventType = LLMEventType.COMPLETED


@dataclass(frozen=True)
class LLMErrorEvent:
    kind: LLMErrorKind
    message: str
    retryable: bool = False
    type: LLMEventType = LLMEventType.ERROR


LLMEvent = (
    LLMStartedEvent
    | LLMTextDeltaEvent
    | LLMToolCallStartedEvent
    | LLMToolCallDeltaEvent
    | LLMToolCallCompletedEvent
    | LLMUsageEvent
    | LLMCompletedEvent
    | LLMErrorEvent
)
