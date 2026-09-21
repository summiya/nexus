from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from nexus.llm.domain import (
    LLMAuthenticationError,
    LLMEvent,
    LLMMessage,
    LLMRequest,
    LLMRole,
    LLMStartedEvent,
    LLMUnknownProviderError,
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
        self.error: BaseException | None = None
        self.exception_types = LiteLLMExceptionTypes(
            authentication=(AuthenticationError,)
        )

    async def acompletion(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response

    async def astream(self, **kwargs: object) -> AsyncIterator[object]:
        self.calls.append(kwargs)
        return _empty_provider_stream()


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


def test_litellm_adapter_generation_cancellation_propagates() -> None:
    fake_client = FakeLiteLLMClient()
    fake_client.error = asyncio.CancelledError()
    request = LLMRequest(
        model="gpt-test",
        messages=[LLMMessage(role=LLMRole.USER, content="Hello")],
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(LiteLLMAdapter(client=fake_client).generate(request))


@pytest.mark.parametrize("arguments", ['{"query"', '["nexus"]'])
def test_litellm_adapter_rejects_invalid_tool_call_arguments_safely(
    arguments: str,
) -> None:
    fake_client = FakeLiteLLMClient()
    fake_client.response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "search",
                                "arguments": arguments,
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    request = LLMRequest(
        model="gpt-test",
        messages=[LLMMessage(role=LLMRole.USER, content="Search")],
    )

    with pytest.raises(LLMUnknownProviderError) as exc_info:
        asyncio.run(LiteLLMAdapter(client=fake_client).generate(request))

    assert exc_info.value.message == "LLM provider returned an invalid tool call"
    assert arguments not in exc_info.value.message


def test_litellm_adapter_does_not_complete_an_empty_provider_stream() -> None:
    fake_client = FakeLiteLLMClient()
    request = LLMRequest(
        model="gpt-test",
        messages=[LLMMessage(role=LLMRole.USER, content="Hello")],
    )

    async def collect_events() -> list[LLMEvent]:
        return [
            event async for event in LiteLLMAdapter(client=fake_client).stream(request)
        ]

    events = asyncio.run(collect_events())

    assert events == [LLMStartedEvent()]


async def _empty_provider_stream() -> AsyncIterator[object]:
    if False:
        yield {}
