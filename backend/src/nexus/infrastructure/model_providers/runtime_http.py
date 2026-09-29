"""Request-scoped HTTPX transport for secure model-provider invocation."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Self, TypeVar, cast
from urllib.parse import SplitResult

import httpx

from nexus.infrastructure.model_providers.outbound_endpoint import (
    HostResolver,
    ResolvedAddress,
    UnsafeProviderEndpointError,
    parse_https_endpoint,
    resolve_public_addresses,
)
from nexus.llm.domain import (
    LLMInvalidRequestError,
    LLMProviderUnavailableError,
    LLMTimeoutError,
)

_T = TypeVar("_T")

_INVALID_ENDPOINT_MESSAGE = "LLM provider endpoint is not supported."
_PROVIDER_UNAVAILABLE_MESSAGE = "LLM provider is temporarily unavailable."
_TIMEOUT_MESSAGE = "LLM provider request timed out."


@dataclass(frozen=True, slots=True)
class RuntimeDeadline:
    """One monotonic deadline shared by every stage of an invocation."""

    expires_at: float
    _clock: Callable[[], float] = time.monotonic

    @classmethod
    def start(
        cls,
        timeout_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> RuntimeDeadline:
        if timeout_seconds <= 0:
            raise ValueError("Runtime timeout must be positive.")
        return cls(expires_at=clock() + timeout_seconds, _clock=clock)

    def remaining_seconds(self) -> float:
        remaining = self.expires_at - self._clock()
        if remaining <= 0:
            raise LLMTimeoutError(_TIMEOUT_MESSAGE)
        return remaining

    async def run(self, operation: Awaitable[_T]) -> _T:
        """Run one stage under the invocation's remaining deadline."""

        try:
            async with asyncio.timeout(self.remaining_seconds()):
                return await operation
        except TimeoutError:
            raise LLMTimeoutError(_TIMEOUT_MESSAGE) from None


@dataclass(slots=True)
class SecureRuntimeHTTPClient:
    """Owned request-scoped HTTP client and its shared runtime deadline."""

    client: httpx.AsyncClient
    deadline: RuntimeDeadline

    async def aclose(self) -> None:
        await self.client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()


class PinnedAsyncHTTPTransport(httpx.AsyncBaseTransport):
    """Connect to one approved address while retaining the TLS/HTTP authority.

    V1 intentionally selects the first address from the fully validated DNS
    answer. It does not retry a generation request against another address,
    because a failed POST may already have reached the provider.
    """

    def __init__(
        self,
        *,
        endpoint: SplitResult,
        address: ResolvedAddress,
        deadline: RuntimeDeadline,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        hostname = endpoint.hostname
        if hostname is None:
            raise LLMInvalidRequestError(_INVALID_ENDPOINT_MESSAGE)
        self._hostname = _normalize_hostname(hostname)
        self._authority = endpoint.netloc
        self._port = endpoint.port or 443
        self._address = address
        self._deadline = deadline
        self._transport = transport or httpx.AsyncHTTPTransport(
            retries=0,
            trust_env=False,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self._require_expected_origin(request.url)
        extensions = dict(request.extensions)
        extensions["sni_hostname"] = self._hostname
        headers = request.headers.copy()
        headers["host"] = self._authority
        pinned_request = httpx.Request(
            method=request.method,
            url=request.url.copy_with(host=self._address.host),
            headers=headers,
            extensions=extensions,
        )
        # Preserve HTTPX's existing asynchronous request stream exactly. Passing
        # it back through ``content=`` would reclassify it as a synchronous
        # iterable at this transport boundary.
        pinned_request.stream = request.stream
        try:
            response = await self._deadline.run(
                self._transport.handle_async_request(pinned_request)
            )
        except asyncio.CancelledError:
            raise
        except LLMTimeoutError:
            raise
        except httpx.TimeoutException:
            raise LLMTimeoutError(_TIMEOUT_MESSAGE) from None
        except (httpx.TransportError, OSError):
            raise LLMProviderUnavailableError(_PROVIDER_UNAVAILABLE_MESSAGE) from None

        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            stream=_DeadlineResponseStream(
                cast(httpx.AsyncByteStream, response.stream),
                self._deadline,
            ),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self._transport.aclose()

    def _require_expected_origin(self, url: httpx.URL) -> None:
        request_port = url.port or (443 if url.scheme.lower() == "https" else 80)
        if (
            url.scheme.lower() != "https"
            or _normalize_hostname(url.host) != self._hostname
            or request_port != self._port
        ):
            raise LLMInvalidRequestError(_INVALID_ENDPOINT_MESSAGE)


class _DeadlineResponseStream(httpx.AsyncByteStream):
    def __init__(
        self,
        stream: httpx.AsyncByteStream,
        deadline: RuntimeDeadline,
    ) -> None:
        self._stream = stream
        self._deadline = deadline

    async def __aiter__(self):
        iterator = self._stream.__aiter__()
        while True:
            try:
                chunk = await self._deadline.run(anext(iterator))
            except StopAsyncIteration:
                return
            except LLMTimeoutError:
                await self._stream.aclose()
                raise
            yield chunk

    async def aclose(self) -> None:
        await self._stream.aclose()


async def create_secure_runtime_http_client(
    *,
    endpoint: str,
    resolver: HostResolver,
    timeout_seconds: float,
) -> SecureRuntimeHTTPClient:
    """Resolve once, validate every answer, and construct a pinned client."""

    deadline = RuntimeDeadline.start(timeout_seconds)
    try:
        parsed = parse_https_endpoint(endpoint)
        addresses = await deadline.run(
            resolve_public_addresses(parsed, resolver=resolver)
        )
    except asyncio.CancelledError:
        raise
    except LLMTimeoutError:
        raise
    except UnsafeProviderEndpointError:
        raise LLMInvalidRequestError(_INVALID_ENDPOINT_MESSAGE) from None
    except OSError:
        raise LLMProviderUnavailableError(_PROVIDER_UNAVAILABLE_MESSAGE) from None

    transport = PinnedAsyncHTTPTransport(
        endpoint=parsed,
        address=addresses[0],
        deadline=deadline,
    )
    return SecureRuntimeHTTPClient(
        client=httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            timeout=None,
        ),
        deadline=deadline,
    )


def _normalize_hostname(hostname: str) -> str:
    return hostname.rstrip(".").lower()


__all__ = [
    "PinnedAsyncHTTPTransport",
    "RuntimeDeadline",
    "SecureRuntimeHTTPClient",
    "create_secure_runtime_http_client",
]
