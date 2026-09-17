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
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        if self.content == "":
            object.__setattr__(self, "content", None)
        if (
            self.role in {LLMRole.SYSTEM, LLMRole.USER, LLMRole.TOOL}
            and self.content is None
        ):
            raise ValueError(f"{self.role.value} message content must not be empty")
        if self.name is not None and not self.name:
            raise ValueError("LLM message name must not be empty")
        if self.tool_call_id is not None and not self.tool_call_id:
            raise ValueError("LLM tool call ID must not be empty")
        if self.role is LLMRole.TOOL and self.tool_call_id is None:
            raise ValueError("tool messages must include a tool call ID")
        if self.role is not LLMRole.TOOL and self.tool_call_id is not None:
            raise ValueError("tool call ID is only valid for tool messages")
