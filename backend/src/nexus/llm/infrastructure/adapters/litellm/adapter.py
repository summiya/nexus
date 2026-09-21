"""LiteLLM-backed LLM gateway adapter."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol

import litellm

from nexus.llm.domain import (
    LLMCompletedEvent,
    LLMError,
    LLMErrorEvent,
    LLMEvent,
    LLMFinishReason,
    LLMRequest,
    LLMResponse,
    LLMStartedEvent,
    LLMUnknownProviderError,
)
from nexus.llm.infrastructure.adapters.litellm.errors import (
    LiteLLMExceptionTypes,
    translate_litellm_error,
)
from nexus.llm.infrastructure.adapters.litellm.mapping import (
    LiteLLMToolCallMappingError,
    to_litellm_payload,
    to_llm_response,
    to_llm_stream_completed_event,
    to_llm_stream_text_delta,
    to_llm_stream_usage_event,
)
from nexus.llm.infrastructure.adapters.litellm.tool_call_assembler import (
    LiteLLMToolCallAssembler,
)


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
        try:
            return to_llm_response(response)
        except LiteLLMToolCallMappingError as exc:
            raise LLMUnknownProviderError(
                "LLM provider returned an invalid tool call"
            ) from exc

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        """Stream normalized events.

        Error policy:
        - provider failure before ``LLMStartedEvent`` raises a Nexus LLM error;
        - provider failure after ``LLMStartedEvent`` yields one ``LLMErrorEvent``;
        - local mapping/programming errors and cancellation propagate after cleanup.

        This adapter exclusively owns and closes the raw provider iterator. Its
        caller owns only this normalized iterator.
        """

        payload = to_litellm_payload(request)
        upstream: AsyncIterator[object] | None = None
        completion: LLMCompletedEvent | None = None
        suppress_cleanup_errors = False
        assembler = LiteLLMToolCallAssembler()

        try:
            try:
                upstream = await self.client.astream(**payload)
            except Exception as exc:
                raise translate_litellm_error(exc, self.client.exception_types) from exc

            yield LLMStartedEvent()
            while True:
                try:
                    chunk = await anext(upstream)
                except StopAsyncIteration:
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - provider boundary
                    error = translate_litellm_error(
                        exc,
                        self.client.exception_types,
                    )
                    yield LLMErrorEvent(
                        kind=error.kind,
                        message=error.message,
                        retryable=error.retryable,
                    )
                    suppress_cleanup_errors = True
                    return

                text_delta = to_llm_stream_text_delta(chunk)
                if text_delta is not None:
                    yield text_delta

                for event in assembler.process_chunk(chunk):
                    yield event

                usage = to_llm_stream_usage_event(chunk)
                if usage is not None:
                    yield usage

                chunk_completion = to_llm_stream_completed_event(chunk)
                if chunk_completion is not None and completion is None:
                    completion = chunk_completion

            if completion is None:
                upstream_to_close = upstream
                upstream = None
                try:
                    await _close_upstream(
                        upstream_to_close,
                        self.client.exception_types,
                        suppress_errors=False,
                    )
                except LLMError as close_error:
                    yield LLMErrorEvent(
                        kind=close_error.kind,
                        message=close_error.message,
                        retryable=close_error.retryable,
                    )
                return

            tool_call_events = assembler.complete()

            if assembler.has_invalid_completion or (
                completion.finish_reason is LLMFinishReason.TOOL_CALLS
                and not tool_call_events
            ):
                error = LLMUnknownProviderError(
                    "LLM provider returned an invalid tool call"
                )
                yield LLMErrorEvent(
                    kind=error.kind,
                    message=error.message,
                    retryable=error.retryable,
                )
                suppress_cleanup_errors = True
                return

            for event in tool_call_events:
                yield event

            upstream_to_close = upstream
            upstream = None
            try:
                await _close_upstream(
                    upstream_to_close,
                    self.client.exception_types,
                    suppress_errors=False,
                )
            except LLMError as close_error:
                yield LLMErrorEvent(
                    kind=close_error.kind,
                    message=close_error.message,
                    retryable=close_error.retryable,
                )
                return
            yield completion
        finally:
            active_exception = sys.exception()
            await _close_upstream(
                upstream,
                self.client.exception_types,
                suppress_errors=suppress_cleanup_errors
                or (
                    active_exception is not None
                    and not isinstance(active_exception, GeneratorExit)
                ),
            )


@dataclass(frozen=True)
class LiteLLMClient:
    """Small reusable wrapper around LiteLLM's async completion API."""

    exception_types: LiteLLMExceptionTypes = field(
        default_factory=lambda: LiteLLMExceptionTypes.from_module(litellm)
    )

    async def acompletion(self, **kwargs: object) -> object:
        return await litellm.acompletion(**kwargs)

    async def astream(self, **kwargs: object) -> AsyncIterator[object]:
        stream = await litellm.acompletion(**kwargs, stream=True)
        return stream


class _LiteLLMClientProtocol(Protocol):
    @property
    def exception_types(self) -> LiteLLMExceptionTypes: ...

    async def acompletion(self, **kwargs: object) -> object: ...

    async def astream(self, **kwargs: object) -> AsyncIterator[object]: ...


async def _close_upstream(
    upstream: AsyncIterator[object] | None,
    exception_types: LiteLLMExceptionTypes,
    *,
    suppress_errors: bool,
) -> None:
    if upstream is None:
        return
    close = getattr(upstream, "aclose", None)
    if not callable(close):
        return
    try:
        await close()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        if suppress_errors:
            return
        raise translate_litellm_error(exc, exception_types) from exc
