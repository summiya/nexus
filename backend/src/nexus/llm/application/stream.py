"""Thin LLM streaming use case."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from nexus.llm.domain import LLMEvent, LLMRequest
from nexus.llm.ports import LLMGateway


@dataclass(frozen=True)
class Stream:
    gateway: LLMGateway

    async def execute(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        async for event in self.gateway.stream(request):
            yield event
