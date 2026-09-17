"""Provider-independent LLM capability contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LLMProviderCapabilities:
    supports_streaming: bool
    supports_tool_calls: bool
    supports_usage: bool
    supports_json_response: bool = False
