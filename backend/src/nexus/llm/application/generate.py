"""Thin non-streaming LLM generation use case."""

from __future__ import annotations

from dataclasses import dataclass

from nexus.llm.domain import LLMRequest, LLMResponse
from nexus.llm.ports import LLMGateway


@dataclass(frozen=True)
class Generate:
    gateway: LLMGateway

    async def execute(self, request: LLMRequest) -> LLMResponse:
        return await self.gateway.generate(request)
