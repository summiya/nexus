"""Provider-runtime execution boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from nexus.llm.domain import (
    EmbeddingRequest,
    EmbeddingResult,
    LLMEvent,
    LLMRequest,
    LLMResponse,
)
from nexus.model_providers.domain import ResolvedChatModel, ResolvedEmbeddingModel


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


class EmbeddingGateway(Protocol):
    """Embed one bounded batch against a separately resolved target.

    Implementations preserve input order, call result.validate_for with the target
    dimension before returning, and expose only Nexus LLMError execution failures.
    Cancellation propagates. No model resolution or batch orchestration belongs here.
    """

    async def embed(
        self, *, request: EmbeddingRequest, target: ResolvedEmbeddingModel
    ) -> EmbeddingResult: ...


__all__ = ["EmbeddingGateway", "RuntimeChatGateway"]
