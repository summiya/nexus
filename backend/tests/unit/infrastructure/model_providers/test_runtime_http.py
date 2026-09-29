from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass, field

import httpx
import pytest

from nexus.infrastructure.model_providers.outbound_endpoint import (
    ResolvedAddress,
    parse_https_endpoint,
)
from nexus.infrastructure.model_providers.runtime_http import (
    PinnedAsyncHTTPTransport,
    RuntimeDeadline,
    create_secure_runtime_http_client,
)
from nexus.llm.domain import (
    LLMInvalidRequestError,
    LLMProviderUnavailableError,
    LLMTimeoutError,
)


@dataclass
class StubResolver:
    answers: tuple[ResolvedAddress, ...] = ()
    error: Exception | None = None
    calls: list[tuple[str, int]] = field(default_factory=list)

    async def resolve(self, *, host: str, port: int) -> tuple[ResolvedAddress, ...]:
        self.calls.append((host, port))
        if self.error is not None:
            raise self.error
        return self.answers


def test_factory_resolves_once_and_selects_first_approved_address() -> None:
    resolver = StubResolver(
        (
            ResolvedAddress("8.8.8.8", socket.AF_INET),
            ResolvedAddress("1.1.1.1", socket.AF_INET),
        )
    )

    async def exercise() -> None:
        resource = await create_secure_runtime_http_client(
            endpoint="https://provider.example/v1",
            resolver=resolver,
            timeout_seconds=10,
        )
        await resource.aclose()

    asyncio.run(exercise())

    assert resolver.calls == [("provider.example", 443)]


def test_factory_maps_unsafe_endpoint_without_exposing_it() -> None:
    endpoint = "http://169.254.169.254/secret"

    async def exercise() -> None:
        with pytest.raises(LLMInvalidRequestError) as captured:
            await create_secure_runtime_http_client(
                endpoint=endpoint,
                resolver=StubResolver(),
                timeout_seconds=10,
            )
        assert str(captured.value) == "LLM provider endpoint is not supported."
        assert endpoint not in str(captured.value)

    asyncio.run(exercise())


def test_factory_maps_dns_failure_without_exposing_hostname_or_error() -> None:
    resolver = StubResolver(error=OSError("secret.example resolution failed"))

    async def exercise() -> None:
        with pytest.raises(LLMProviderUnavailableError) as captured:
            await create_secure_runtime_http_client(
                endpoint="https://secret.example/v1",
                resolver=resolver,
                timeout_seconds=10,
            )
        assert str(captured.value) == "LLM provider is temporarily unavailable."
        assert "secret.example" not in str(captured.value)

    asyncio.run(exercise())


def test_transport_connects_to_pinned_ip_and_preserves_host_and_sni() -> None:
    observed: dict[str, object] = {}

    async def respond(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["host"] = request.headers["host"]
        observed["sni"] = request.extensions["sni_hostname"]
        return httpx.Response(200, json={"ok": True})

    async def exercise() -> None:
        transport = PinnedAsyncHTTPTransport(
            endpoint=parse_https_endpoint("https://provider.example/v1"),
            address=ResolvedAddress("8.8.8.8", socket.AF_INET),
            deadline=RuntimeDeadline.start(10),
            transport=httpx.MockTransport(respond),
        )
        async with httpx.AsyncClient(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            response = await client.get("https://provider.example/v1/models?q=1")
            assert response.status_code == 200

    asyncio.run(exercise())

    assert observed == {
        "url": "https://8.8.8.8/v1/models?q=1",
        "host": "provider.example",
        "sni": "provider.example",
    }


def test_transport_rejects_origin_drift_before_inner_transport() -> None:
    calls = 0

    async def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    async def exercise() -> None:
        transport = PinnedAsyncHTTPTransport(
            endpoint=parse_https_endpoint("https://provider.example/v1"),
            address=ResolvedAddress("8.8.8.8", socket.AF_INET),
            deadline=RuntimeDeadline.start(10),
            transport=httpx.MockTransport(respond),
        )
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(LLMInvalidRequestError):
                await client.get("https://other.example/v1/models")

    asyncio.run(exercise())
    assert calls == 0


def test_client_does_not_follow_redirects() -> None:
    calls: list[str] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://other.example/"})

    async def exercise() -> None:
        transport = PinnedAsyncHTTPTransport(
            endpoint=parse_https_endpoint("https://provider.example/v1"),
            address=ResolvedAddress("8.8.8.8", socket.AF_INET),
            deadline=RuntimeDeadline.start(10),
            transport=httpx.MockTransport(respond),
        )
        async with httpx.AsyncClient(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            response = await client.get("https://provider.example/v1/models")
            assert response.status_code == 302

    asyncio.run(exercise())
    assert calls == ["https://8.8.8.8/v1/models"]


class BlockingStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.closed = False

    async def __aiter__(self):
        await asyncio.Event().wait()
        yield b"unreachable"

    async def aclose(self) -> None:
        self.closed = True


def test_runtime_deadline_covers_stream_reads_and_closes_stream() -> None:
    stream = BlockingStream()

    async def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    async def exercise() -> None:
        transport = PinnedAsyncHTTPTransport(
            endpoint=parse_https_endpoint("https://provider.example/v1"),
            address=ResolvedAddress("8.8.8.8", socket.AF_INET),
            deadline=RuntimeDeadline.start(0.01),
            transport=httpx.MockTransport(respond),
        )
        async with (
            httpx.AsyncClient(transport=transport) as client,
            client.stream("GET", "https://provider.example/v1/models") as response,
        ):
            with pytest.raises(LLMTimeoutError, match="request timed out"):
                await response.aread()

    asyncio.run(exercise())
    assert stream.closed is True


def test_dns_resolution_is_covered_by_runtime_deadline() -> None:
    class BlockingResolver:
        async def resolve(self, *, host: str, port: int) -> tuple[ResolvedAddress, ...]:
            del host, port
            await asyncio.Event().wait()
            return ()

    async def exercise() -> None:
        with pytest.raises(LLMTimeoutError, match="request timed out"):
            await create_secure_runtime_http_client(
                endpoint="https://provider.example/v1",
                resolver=BlockingResolver(),
                timeout_seconds=0.01,
            )

    asyncio.run(exercise())
