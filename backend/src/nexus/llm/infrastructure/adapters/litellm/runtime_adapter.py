"""Secure LiteLLM implementation of the organization runtime chat gateway."""

from __future__ import annotations

import asyncio
import inspect
import sys
from collections.abc import AsyncIterator, Coroutine
from dataclasses import dataclass, field
from typing import Protocol

from openai import AsyncAzureOpenAI, AsyncOpenAI

from nexus.infrastructure.model_providers.outbound_endpoint import (
    HostResolver,
    SystemHostResolver,
)
from nexus.infrastructure.model_providers.runtime_http import (
    SecureRuntimeHTTPClient,
    create_secure_runtime_http_client,
)
from nexus.llm.domain import (
    LLMError,
    LLMEvent,
    LLMInvalidRequestError,
    LLMProviderUnavailableError,
    LLMRequest,
    LLMResponse,
)
from nexus.llm.infrastructure.adapters.litellm.adapter import (
    LiteLLMAdapter,
    LiteLLMClient,
)
from nexus.llm.infrastructure.adapters.litellm.errors import LiteLLMExceptionTypes
from nexus.llm.infrastructure.adapters.litellm.runtime_http import (
    PinnedLiteLLMAsyncHTTPHandler,
)
from nexus.llm.infrastructure.adapters.litellm.runtime_mapping import (
    LiteLLMRuntimeMapping,
    RuntimeClientKind,
    map_runtime_target,
)
from nexus.model_providers.domain import ResolvedChatModel
from nexus.model_providers.ports.runtime import RuntimeChatGateway

_INVALID_TARGET = "LLM runtime target is invalid."
_CLEANUP_FAILURE = "LLM provider is temporarily unavailable."


class RuntimeHTTPClientFactory(Protocol):
    async def __call__(
        self,
        *,
        endpoint: str,
        resolver: HostResolver,
        timeout_seconds: float,
    ) -> SecureRuntimeHTTPClient: ...


class _LiteLLMRuntimeClient(Protocol):
    @property
    def exception_types(self) -> LiteLLMExceptionTypes: ...

    async def acompletion(self, **kwargs: object) -> object: ...

    async def astream(self, **kwargs: object) -> AsyncIterator[object]: ...


@dataclass(frozen=True)
class LiteLLMRuntimeAdapter(RuntimeChatGateway):
    """Execute resolved targets with isolated credentials and pinned transport."""

    timeout_seconds: float
    resolver: HostResolver = field(default_factory=SystemHostResolver)
    http_client_factory: RuntimeHTTPClientFactory = (
        create_secure_runtime_http_client
    )
    litellm_client: _LiteLLMRuntimeClient = field(default_factory=LiteLLMClient)

    async def generate(
        self,
        *,
        request: LLMRequest,
        target: ResolvedChatModel,
    ) -> LLMResponse:
        resources = await self._build_resources(target)
        active_error = False
        try:
            adapter = LiteLLMAdapter(
                client=_RuntimeInvocationClient(
                    base=self.litellm_client,
                    invocation_arguments=resources.invocation_arguments,
                )
            )
            return await resources.http.deadline.run(adapter.generate(request))
        except BaseException:
            active_error = True
            raise
        finally:
            await _finish_cleanup(resources.aclose(suppress_errors=active_error))

    async def stream(
        self,
        *,
        request: LLMRequest,
        target: ResolvedChatModel,
    ) -> AsyncIterator[LLMEvent]:
        resources: _RuntimeResources | None = None
        upstream: AsyncIterator[LLMEvent] | None = None
        try:
            resources = await self._build_resources(target)
            adapter = LiteLLMAdapter(
                client=_RuntimeInvocationClient(
                    base=self.litellm_client,
                    invocation_arguments=resources.invocation_arguments,
                )
            )
            upstream = adapter.stream(request)
            while True:
                try:
                    event = await resources.http.deadline.run(anext(upstream))
                except StopAsyncIteration:
                    return
                yield event
        finally:
            active_error = sys.exception() is not None
            await _finish_cleanup(
                _close_stream_resources(
                    upstream,
                    resources,
                    suppress_errors=active_error,
                )
            )

    async def _build_resources(
        self,
        target: ResolvedChatModel,
    ) -> _RuntimeResources:
        mapping = map_runtime_target(target)
        http = await self.http_client_factory(
            endpoint=mapping.endpoint,
            resolver=self.resolver,
            timeout_seconds=self.timeout_seconds,
        )
        try:
            secret = target.credential.reveal()
            provider_client = _build_provider_client(mapping, secret, http)
            arguments = mapping.invocation_arguments()
            arguments["api_key"] = secret
            arguments["client"] = provider_client
            return _RuntimeResources(
                http=http,
                provider_client=provider_client,
                invocation_arguments=arguments,
            )
        except asyncio.CancelledError:
            await _finish_cleanup(http.aclose())
            raise
        except LLMError:
            await _finish_cleanup(http.aclose())
            raise
        except Exception:  # noqa: BLE001 - sanitize client construction failures
            await _finish_cleanup(http.aclose())
            raise LLMInvalidRequestError(_INVALID_TARGET) from None


@dataclass(slots=True)
class _RuntimeResources:
    http: SecureRuntimeHTTPClient
    provider_client: object
    invocation_arguments: dict[str, object]

    async def aclose(self, *, suppress_errors: bool) -> None:
        try:
            close = getattr(self.provider_client, "close", None)
            if callable(close):
                result = close()
                if inspect.isawaitable(result):
                    await result
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - provider client cleanup boundary
            if not suppress_errors:
                raise LLMProviderUnavailableError(_CLEANUP_FAILURE) from None
        finally:
            try:
                await self.http.aclose()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - owned transport cleanup boundary
                if not suppress_errors:
                    raise LLMProviderUnavailableError(_CLEANUP_FAILURE) from None


@dataclass(frozen=True)
class _RuntimeInvocationClient:
    base: _LiteLLMRuntimeClient
    invocation_arguments: dict[str, object]

    @property
    def exception_types(self) -> LiteLLMExceptionTypes:
        return self.base.exception_types

    async def acompletion(self, **kwargs: object) -> object:
        return await self.base.acompletion(**self._arguments(kwargs))

    async def astream(self, **kwargs: object) -> AsyncIterator[object]:
        return await self.base.astream(**self._arguments(kwargs))

    def _arguments(self, semantic: dict[str, object]) -> dict[str, object]:
        arguments = dict(semantic)
        arguments.update(self.invocation_arguments)
        return arguments


def _build_provider_client(
    mapping: LiteLLMRuntimeMapping,
    secret: str,
    http: SecureRuntimeHTTPClient,
) -> object:
    if mapping.client_kind is RuntimeClientKind.OPENAI:
        return AsyncOpenAI(
            api_key=secret,
            base_url=mapping.api_base or mapping.endpoint,
            http_client=http.client,
        )
    if mapping.client_kind is RuntimeClientKind.AZURE_OPENAI:
        if mapping.api_version is None:
            raise LLMInvalidRequestError(_INVALID_TARGET)
        return AsyncAzureOpenAI(
            api_key=secret,
            azure_endpoint=mapping.endpoint,
            api_version=mapping.api_version,
            http_client=http.client,
        )
    return PinnedLiteLLMAsyncHTTPHandler(http.client)


async def _close_iterator(
    iterator: AsyncIterator[LLMEvent] | None,
    *,
    suppress_errors: bool,
) -> None:
    if iterator is None:
        return
    close = getattr(iterator, "aclose", None)
    if not callable(close):
        return
    try:
        await close()
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - upstream iterator cleanup boundary
        if not suppress_errors:
            raise LLMProviderUnavailableError(_CLEANUP_FAILURE) from None


async def _close_stream_resources(
    iterator: AsyncIterator[LLMEvent] | None,
    resources: _RuntimeResources | None,
    *,
    suppress_errors: bool,
) -> None:
    try:
        await _close_iterator(iterator, suppress_errors=suppress_errors)
    finally:
        if resources is not None:
            await resources.aclose(suppress_errors=suppress_errors)


async def _finish_cleanup(cleanup: Coroutine[object, object, None]) -> None:
    """Complete owned-resource cleanup before propagating cancellation."""

    task = asyncio.create_task(cleanup)
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            cancellation = exc
        except BaseException:  # noqa: BLE001 - re-raised through task.result below
            break

    if cancellation is not None:
        if not task.cancelled():
            task.exception()
        raise cancellation
    task.result()


__all__ = ["LiteLLMRuntimeAdapter", "RuntimeHTTPClientFactory"]
