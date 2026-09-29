from __future__ import annotations

import asyncio

import httpx
import pytest

from litellm.exceptions import (
    APIConnectionError,
    BadRequestError,
    Timeout,
)
from nexus.llm.domain import (
    LLMInvalidRequestError,
    LLMProviderUnavailableError,
    LLMTimeoutError,
)
from nexus.llm.infrastructure.adapters.litellm.runtime_http import (
    PinnedLiteLLMAsyncHTTPHandler,
)


def test_handler_uses_borrowed_client_without_owning_its_lifecycle() -> None:
    requests: list[httpx.Request] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    async def exercise() -> None:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(respond),
            trust_env=False,
            follow_redirects=False,
        )
        handler = PinnedLiteLLMAsyncHTTPHandler(client)

        response = await handler.post(
            "https://provider.example/messages",
            json={"model": "model-a"},
            headers={"x-api-key": "request-key"},
        )
        assert response.status_code == 200

        await handler.close()
        assert client.is_closed is False
        await client.aclose()

    asyncio.run(exercise())

    assert len(requests) == 1
    assert requests[0].headers["x-api-key"] == "request-key"
    assert requests[0].url == httpx.URL("https://provider.example/messages")


def test_handler_streams_through_the_supplied_client() -> None:
    calls = 0

    async def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"stream-content")

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond),
            trust_env=False,
            follow_redirects=False,
        ) as client:
            handler = PinnedLiteLLMAsyncHTTPHandler(client)
            response = await handler.post(
                "https://provider.example/messages",
                stream=True,
            )
            assert await response.aread() == b"stream-content"
            await response.aclose()

    asyncio.run(exercise())
    assert calls == 1


def test_handler_sanitizes_non_success_response_before_raising() -> None:
    sentinel = "provider-secret-error-body"

    async def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, content=sentinel.encode())

    async def exercise() -> httpx.HTTPStatusError:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond),
            trust_env=False,
            follow_redirects=False,
        ) as client:
            handler = PinnedLiteLLMAsyncHTTPHandler(client)
            with pytest.raises(httpx.HTTPStatusError) as captured:
                await handler.post(
                    "https://tenant-endpoint.example/messages",
                    stream=True,
                )
            return captured.value

    error = asyncio.run(exercise())

    assert error.response.status_code == 401
    assert error.response.content == b""
    rendered = f"{error!r} {error}"
    assert sentinel not in rendered
    assert "tenant-endpoint.example" not in rendered


@pytest.mark.parametrize(
    ("source_error", "expected_type"),
    [
        (LLMTimeoutError("secret timeout detail"), Timeout),
        (
            LLMProviderUnavailableError("secret connection detail"),
            APIConnectionError,
        ),
        (LLMInvalidRequestError("secret endpoint detail"), BadRequestError),
    ],
)
def test_handler_maps_nexus_transport_errors_to_litellm_types(
    source_error: Exception,
    expected_type: type[Exception],
) -> None:
    async def respond(_request: httpx.Request) -> httpx.Response:
        raise source_error

    async def exercise() -> Exception:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond),
            trust_env=False,
            follow_redirects=False,
        ) as client:
            handler = PinnedLiteLLMAsyncHTTPHandler(client)
            with pytest.raises(expected_type) as captured:
                await handler.post("https://provider.example/messages")
            return captured.value

    error = asyncio.run(exercise())

    rendered = f"{error!r} {error}"
    assert "secret timeout detail" not in rendered
    assert "secret connection detail" not in rendered
    assert "secret endpoint detail" not in rendered
