"""LiteLLM-backed LLM gateway adapter."""

from __future__ import annotations

import importlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from types import ModuleType

from nexus.llm.domain import LLMEvent, LLMRequest, LLMResponse
from nexus.llm.infrastructure.adapters.litellm.errors import (
    LiteLLMExceptionTypes,
    load_litellm_exception_types,
    translate_litellm_error,
)
from nexus.llm.infrastructure.adapters.litellm.mapping import (
    to_litellm_payload,
    to_llm_response,
)


@dataclass(frozen=True)
class LiteLLMAdapter:
    """Concrete non-streaming LiteLLM implementation of the LLMGateway port."""

    async def generate(self, request: LLMRequest) -> LLMResponse:
        payload = to_litellm_payload(request)
        client = _load_litellm_client()
        try:
            response = await client.acompletion(**payload)
        except Exception as exc:
            raise translate_litellm_error(exc, client.exception_types) from exc
        return to_llm_response(response)

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        del request
        return _streaming_not_implemented()


@dataclass(frozen=True)
class _LiteLLMClient:
    module: ModuleType
    exception_types: LiteLLMExceptionTypes

    async def acompletion(self, **kwargs: object) -> object:
        return await self.module.acompletion(**kwargs)


def _load_litellm_client() -> _LiteLLMClient:
    try:
        module = importlib.import_module("litellm")
    except ModuleNotFoundError as exc:
        raise translate_litellm_error(exc, LiteLLMExceptionTypes()) from exc
    return _LiteLLMClient(
        module=module,
        exception_types=load_litellm_exception_types(module),
    )


async def _streaming_not_implemented() -> AsyncIterator[LLMEvent]:
    raise NotImplementedError("LiteLLM streaming is not implemented in Phase 2")
    yield  # pragma: no cover
