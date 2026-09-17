"""Thin LLM streaming use case."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from nexus.llm.domain import LLMEvent, LLMRequest
from nexus.llm.ports import LLMGateway


@dataclass(frozen=True)
class Stream:
    gateway: LLMGateway

    def execute(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        """Return the gateway stream directly so downstream close propagates."""

        return self.gateway.stream(request)
