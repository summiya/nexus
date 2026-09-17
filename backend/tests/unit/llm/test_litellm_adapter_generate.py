from __future__ import annotations

import asyncio
from typing import Any

import pytest

from nexus.llm.domain import (
    LLMAuthenticationError,
    LLMMessage,
    LLMRequest,
    LLMRole,
)
from nexus.llm.infrastructure.adapters.litellm import LiteLLMAdapter
from nexus.llm.infrastructure.adapters.litellm.errors import LiteLLMExceptionTypes


class AuthenticationError(Exception):
    pass


class FakeLiteLLMClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.response: object = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Hello"},
                    "finish_reason": "stop",
                }
            ]
        }
        self.error: Exception | None = None
        self.exception_types = LiteLLMExceptionTypes(
            authentication=(AuthenticationError,)
        )

    async def acompletion(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


def test_litellm_adapter_calls_async_api_and_maps_response() -> None:
    fake_client = FakeLiteLLMClient()
    request = LLMRequest(
        model="gpt-test",
        messages=[LLMMessage(role=LLMRole.USER, content="Hello")],
        temperature=0.1,
    )

    response = asyncio.run(LiteLLMAdapter(client=fake_client).generate(request))

    assert fake_client.calls == [
        {
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "Hello"}],
            "temperature": 0.1,
        }
    ]
    assert response.message.content == "Hello"


def test_litellm_adapter_translates_provider_errors() -> None:
    fake_client = FakeLiteLLMClient()
    fake_client.error = AuthenticationError("api-key-secret")
    request = LLMRequest(
        model="gpt-test",
        messages=[LLMMessage(role=LLMRole.USER, content="Hello")],
    )

    with pytest.raises(LLMAuthenticationError) as exc_info:
        asyncio.run(LiteLLMAdapter(client=fake_client).generate(request))

    assert exc_info.value.message == "LLM provider request failed"
    assert "api-key-secret" not in exc_info.value.message


def test_litellm_adapter_does_not_fake_streaming() -> None:
    request = LLMRequest(
        model="gpt-test",
        messages=[LLMMessage(role=LLMRole.USER, content="Hello")],
    )

    async def consume_stream() -> None:
        async for _event in LiteLLMAdapter().stream(request):
            pass

    with pytest.raises(NotImplementedError, match="Phase 2"):
        asyncio.run(consume_stream())
