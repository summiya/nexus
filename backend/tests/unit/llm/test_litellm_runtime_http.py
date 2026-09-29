from __future__ import annotations

import asyncio

import httpx

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
