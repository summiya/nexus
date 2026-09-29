"""Characterize request-scoped client injection in the pinned LiteLLM release."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

import httpx
import pytest
from openai import AsyncAzureOpenAI, AsyncOpenAI

from nexus.config.litellm import require_local_litellm_metadata
from nexus.llm.infrastructure.adapters.litellm.runtime_http import (
    PinnedLiteLLMAsyncHTTPHandler,
)

require_local_litellm_metadata()
import litellm


@dataclass(frozen=True)
class ProviderCase:
    name: str
    base_url: str
    response: dict[str, object]
    build_kwargs: Callable[[httpx.AsyncClient], dict[str, object]]


def _openai_kwargs(client: httpx.AsyncClient) -> dict[str, object]:
    return {
        "model": "openai/gpt-4o-mini",
        "api_key": "request-openai-key",
        "client": AsyncOpenAI(
            api_key="request-openai-key",
            base_url="https://request-openai.example/v1",
            http_client=client,
        ),
    }


def _azure_kwargs(client: httpx.AsyncClient) -> dict[str, object]:
    return {
        "model": "azure/request-deployment",
        "api_key": "request-azure-key",
        "api_base": "https://request-azure.example",
        "api_version": "2025-01-01-preview",
        "client": AsyncAzureOpenAI(
            api_key="request-azure-key",
            azure_endpoint="https://request-azure.example",
            api_version="2025-01-01-preview",
            http_client=client,
        ),
    }


def _anthropic_kwargs(client: httpx.AsyncClient) -> dict[str, object]:
    return {
        "model": "anthropic/claude-sonnet-4-20250514",
        "api_key": "request-anthropic-key",
        "api_base": "https://api.anthropic.com",
        "client": PinnedLiteLLMAsyncHTTPHandler(client),
        "rust": False,
    }


def _gemini_kwargs(client: httpx.AsyncClient) -> dict[str, object]:
    return {
        "model": "gemini/gemini-2.0-flash",
        "api_key": "request-gemini-key",
        "api_base": "https://generativelanguage.googleapis.com",
        "client": PinnedLiteLLMAsyncHTTPHandler(client),
    }


CASES = (
    ProviderCase(
        name="openai",
        base_url="https://request-openai.example/v1",
        response={
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 1,
            "model": "gpt-4o-mini",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
        build_kwargs=_openai_kwargs,
    ),
    ProviderCase(
        name="azure",
        base_url="https://request-azure.example",
        response={
            "id": "chatcmpl-2",
            "object": "chat.completion",
            "created": 1,
            "model": "request-deployment",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
        build_kwargs=_azure_kwargs,
    ),
    ProviderCase(
        name="anthropic",
        base_url="https://api.anthropic.com",
        response={
            "id": "msg-1",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-20250514",
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
        build_kwargs=_anthropic_kwargs,
    ),
    ProviderCase(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com",
        response={
            "candidates": [
                {
                    "content": {"parts": [{"text": "ok"}], "role": "model"},
                    "finishReason": "STOP",
                    "index": 0,
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 1,
                "candidatesTokenCount": 1,
                "totalTokenCount": 2,
            },
        },
        build_kwargs=_gemini_kwargs,
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_request_scoped_clients_override_conflicting_global_configuration(
    case: ProviderCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=case.response)

    monkeypatch.setenv("OPENAI_API_KEY", "global-openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "global-anthropic-key")
    monkeypatch.setenv("GEMINI_API_KEY", "global-gemini-key")
    monkeypatch.setattr(litellm, "api_key", "global-litellm-key")
    monkeypatch.setattr(litellm, "api_base", "https://global-invalid.example")

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond),
            trust_env=False,
            follow_redirects=False,
        ) as client:
            kwargs = case.build_kwargs(client)
            await litellm.acompletion(
                messages=[{"role": "user", "content": "hello"}],
                **kwargs,
            )

    asyncio.run(exercise())

    assert len(requests) == 1
    assert str(requests[0].url).startswith(case.base_url)
    assert "global-invalid.example" not in str(requests[0].url)
    assert b"global-litellm-key" not in requests[0].content


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_streaming_acompletion_uses_the_supplied_request_scoped_client(
    case: ProviderCase,
) -> None:
    requests: list[httpx.Request] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"")

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond),
            trust_env=False,
            follow_redirects=False,
        ) as client:
            stream = await litellm.acompletion(
                messages=[{"role": "user", "content": "hello"}],
                stream=True,
                **case.build_kwargs(client),
            )
            try:
                await anext(stream)
            except StopAsyncIteration:
                pass
            await stream.aclose()

    asyncio.run(exercise())

    assert len(requests) == 1
    assert str(requests[0].url).startswith(case.base_url)
