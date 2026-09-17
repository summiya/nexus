"""Provider-independent LLM message contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LLMRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True)
class LLMMessage:
    role: LLMRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        if not self.content:
            raise ValueError("LLM message content must not be empty")
        if self.name is not None and not self.name:
            raise ValueError("LLM message name must not be empty")
        if self.tool_call_id is not None and not self.tool_call_id:
            raise ValueError("LLM tool call ID must not be empty")
