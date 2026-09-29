"""Provider-runtime execution boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from nexus.llm.domain import LLMEvent, LLMRequest, LLMResponse
from nexus.model_providers.domain import ResolvedChatModel


class RuntimeChatGateway(Protocol):
    """Execute semantic chat requests against one resolved runtime target."""

    async def generate(
        self,
        *,
        request: LLMRequest,
        target: ResolvedChatModel,
    ) -> LLMResponse: ...

    def stream(
        self,
        *,
        request: LLMRequest,
        target: ResolvedChatModel,
    ) -> AsyncIterator[LLMEvent]: ...


__all__ = ["RuntimeChatGateway"]
