"""Provider-independent LLM usage contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        if self.input_tokens < 0:
            raise ValueError("input token count must not be negative")
        if self.output_tokens < 0:
            raise ValueError("output token count must not be negative")
        if self.total_tokens < 0:
            raise ValueError("total token count must not be negative")
