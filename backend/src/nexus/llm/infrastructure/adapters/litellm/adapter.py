"""LiteLLM-backed LLM gateway adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol

from nexus.llm.domain import LLMEvent, LLMRequest, LLMResponse
from nexus.llm.infrastructure.adapters.litellm.errors import (
    LiteLLMExceptionTypes,
    translate_litellm_error,
)
from nexus.llm.infrastructure.adapters.litellm.mapping import (
    to_litellm_payload,
    to_llm_response,
)

try:
    import litellm  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - package metadata declares dependency
    litellm = None  # type: ignore[assignment]


@dataclass(frozen=True)
class LiteLLMAdapter:
    """Concrete non-streaming LiteLLM implementation of the LLMGateway port."""

    client: _LiteLLMClientProtocol = field(default_factory=lambda: LiteLLMClient())

    async def generate(self, request: LLMRequest) -> LLMResponse:
        payload = to_litellm_payload(request)
        try:
            response = await self.client.acompletion(**payload)
        except Exception as exc:
            raise translate_litellm_error(exc, self.client.exception_types) from exc
        return to_llm_response(response)

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        del request
        return _streaming_not_implemented()


@dataclass(frozen=True)
class LiteLLMClient:
    """Small reusable wrapper around LiteLLM's async completion API."""

    exception_types: LiteLLMExceptionTypes = field(
        default_factory=lambda: LiteLLMExceptionTypes.from_module(litellm)
    )

    async def acompletion(self, **kwargs: object) -> object:
        module = litellm
        if module is None:
            raise RuntimeError("LiteLLM dependency is not installed")
        return await module.acompletion(**kwargs)


class _LiteLLMClientProtocol(Protocol):
    @property
    def exception_types(self) -> LiteLLMExceptionTypes: ...

    async def acompletion(self, **kwargs: object) -> object: ...


async def _streaming_not_implemented() -> AsyncIterator[LLMEvent]:
    raise NotImplementedError("LiteLLM streaming is not implemented in Phase 2")
    yield  # pragma: no cover
