from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest

from nexus.llm.domain import (
    LLMAuthenticationError,
    LLMCompletedEvent,
    LLMError,
    LLMErrorEvent,
    LLMEvent,
    LLMEventType,
    LLMFinishReason,
    LLMMessage,
    LLMProviderUnavailableError,
    LLMRequest,
    LLMRole,
    LLMStartedEvent,
    LLMTextDeltaEvent,
    LLMToolCallCompletedEvent,
    LLMToolCallDeltaEvent,
    LLMToolCallStartedEvent,
    LLMUnknownProviderError,
    LLMUsage,
    LLMUsageEvent,
)
from nexus.llm.infrastructure.adapters.litellm import LiteLLMAdapter
from nexus.llm.infrastructure.adapters.litellm.errors import LiteLLMExceptionTypes


class AuthenticationError(Exception):
    pass


class APIConnectionError(Exception):
    pass


class FakeLiteLLMClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.stream: FakeAsyncStream | None = FakeAsyncStream([])
        self.stream_error: Exception | None = None
        self.exception_types = LiteLLMExceptionTypes(
            authentication=(AuthenticationError,),
            provider_unavailable=(APIConnectionError,),
        )

    async def acompletion(self, **kwargs: object) -> object:
        del kwargs
        raise AssertionError("stream tests must not call non-streaming completion")

    async def astream(self, **kwargs: object) -> AsyncIterator[object]:
        self.calls.append(kwargs)
        if self.stream_error is not None:
            raise self.stream_error
        if self.stream is None:
            raise AssertionError("test stream was not configured")
        return self.stream


class FakeAsyncStream:
    def __init__(
        self,
        chunks: Sequence[object],
        *,
        error: Exception | None = None,
        error_after_chunks: bool = False,
        close_error: Exception | None = None,
    ) -> None:
        self._chunks = list(chunks)
        self._error = error
        self._error_after_chunks = error_after_chunks
        self._close_error = close_error
        self._index = 0
        self.closed = False
        self.close_count = 0

    def __aiter__(self) -> FakeAsyncStream:
        return self

    async def __anext__(self) -> object:
        if self._error is not None and not self._error_after_chunks:
            raise self._error
        if self._index >= len(self._chunks):
            if self._error is not None:
                raise self._error
            raise StopAsyncIteration
        value = self._chunks[self._index]
        self._index += 1
        return value

    async def aclose(self) -> None:
        self.close_count += 1
        self.closed = True
        if self._close_error is not None:
            raise self._close_error


class CancellingAsyncStream(FakeAsyncStream):
    async def __anext__(self) -> object:
        raise asyncio.CancelledError


def request() -> LLMRequest:
    return LLMRequest(
        model="gpt-test",
        messages=[LLMMessage(role=LLMRole.USER, content="Hello")],
    )


def chunk(
    *,
    content: str | None = None,
    finish_reason: str | None = None,
    usage: dict[str, int] | None = None,
    tool_calls: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    delta: dict[str, object] = {}
    if content is not None:
        delta["content"] = content
    if tool_calls is not None:
        delta["tool_calls"] = tool_calls
    return {
        "choices": [{"delta": delta, "finish_reason": finish_reason}],
        "usage": usage,
    }


def usage_only_chunk(*, input_tokens: int, output_tokens: int) -> dict[str, object]:
    return {
        "choices": [],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


async def collect_events(adapter: LiteLLMAdapter) -> list[LLMEvent]:
    return [event async for event in adapter.stream(request())]


def assert_no_completed(events: Sequence[LLMEvent]) -> None:
    assert not any(event.type is LLMEventType.COMPLETED for event in events)


def test_stream_maps_text_usage_and_completion() -> None:
    fake_client = FakeLiteLLMClient()
    fake_client.stream = FakeAsyncStream(
        [
            chunk(content=""),
            chunk(content="Hel"),
            chunk(content="lo"),
            chunk(
                finish_reason="stop",
                usage={
                    "prompt_tokens": 3,
                    "completion_tokens": 2,
                    "total_tokens": 5,
                },
            ),
        ]
    )

    events = asyncio.run(collect_events(LiteLLMAdapter(client=fake_client)))

    assert fake_client.calls == [
        {
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "Hello"}],
        }
    ]
    assert events == [
        LLMStartedEvent(),
        LLMTextDeltaEvent(delta="Hel"),
        LLMTextDeltaEvent(delta="lo"),
        LLMUsageEvent(usage=LLMUsage(input_tokens=3, output_tokens=2, total_tokens=5)),
        LLMCompletedEvent(finish_reason=LLMFinishReason.STOP),
    ]
    assert [event.type for event in events].count(LLMEventType.STARTED) == 1
    assert [event.type for event in events].count(LLMEventType.COMPLETED) == 1


def test_stream_keeps_first_finish_reason_and_emits_completion_once() -> None:
    fake_client = FakeLiteLLMClient()
    stream = FakeAsyncStream(
        [
            chunk(content="Hel"),
            chunk(finish_reason="stop"),
            chunk(finish_reason="length"),
        ]
    )
    fake_client.stream = stream

    events = asyncio.run(collect_events(LiteLLMAdapter(client=fake_client)))

    assert events == [
        LLMStartedEvent(),
        LLMTextDeltaEvent(delta="Hel"),
        LLMCompletedEvent(finish_reason=LLMFinishReason.STOP),
    ]
    assert stream.close_count == 1


def test_stream_accepts_usage_only_chunk_after_finish_reason() -> None:
    fake_client = FakeLiteLLMClient()
    fake_client.stream = FakeAsyncStream(
        [
            chunk(content="Hel"),
            chunk(finish_reason="stop"),
            usage_only_chunk(input_tokens=3, output_tokens=1),
        ]
    )

    events = asyncio.run(collect_events(LiteLLMAdapter(client=fake_client)))

    assert events == [
        LLMStartedEvent(),
        LLMTextDeltaEvent(delta="Hel"),
        LLMUsageEvent(usage=LLMUsage(input_tokens=3, output_tokens=1, total_tokens=4)),
        LLMCompletedEvent(finish_reason=LLMFinishReason.STOP),
    ]


def test_stream_maps_tool_call_deltas_and_completion() -> None:
    fake_client = FakeLiteLLMClient()
    fake_client.stream = FakeAsyncStream(
        [
            chunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call_1",
                        "function": {
                            "name": "search",
                            "arguments": '{"query"',
                        },
                    }
                ]
            ),
            chunk(
                tool_calls=[
                    {
                        "index": 0,
                        "function": {"arguments": ': "nexus"}'},
                    }
                ],
                finish_reason="tool_calls",
            ),
        ]
    )

    events = asyncio.run(collect_events(LiteLLMAdapter(client=fake_client)))

    assert events[:4] == [
        LLMStartedEvent(),
        LLMToolCallStartedEvent(tool_call_id="call_1", name="search"),
        LLMToolCallDeltaEvent(tool_call_id="call_1", arguments_delta='{"query"'),
        LLMToolCallDeltaEvent(tool_call_id="call_1", arguments_delta=': "nexus"}'),
    ]
    assert events[4] == LLMToolCallCompletedEvent(
        tool_call=events[4].tool_call  # type: ignore[union-attr]
    )
    assert isinstance(events[4], LLMToolCallCompletedEvent)
    assert events[4].tool_call.id == "call_1"
    assert events[4].tool_call.name == "search"
    assert events[4].tool_call.arguments == {"query": "nexus"}
    assert events[5] == LLMCompletedEvent(finish_reason=LLMFinishReason.TOOL_CALLS)


def test_tool_call_arguments_wait_for_stable_identity() -> None:
    fake_client = FakeLiteLLMClient()
    fake_client.stream = FakeAsyncStream(
        [
            chunk(
                tool_calls=[
                    {
                        "index": 0,
                        "function": {"arguments": '{"query"'},
                    }
                ]
            ),
            chunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call_1",
                        "function": {
                            "name": "search",
                            "arguments": ': "nexus"}',
                        },
                    }
                ],
                finish_reason="tool_calls",
            ),
        ]
    )

    events = asyncio.run(collect_events(LiteLLMAdapter(client=fake_client)))

    assert events[:4] == [
        LLMStartedEvent(),
        LLMToolCallStartedEvent(tool_call_id="call_1", name="search"),
        LLMToolCallDeltaEvent(tool_call_id="call_1", arguments_delta='{"query"'),
        LLMToolCallDeltaEvent(tool_call_id="call_1", arguments_delta=': "nexus"}'),
    ]
    assert isinstance(events[4], LLMToolCallCompletedEvent)
    assert events[4].tool_call.id == "call_1"
    assert events[4].tool_call.name == "search"
    assert events[4].tool_call.arguments == {"query": "nexus"}


def test_stream_maps_interleaved_tool_calls_independently() -> None:
    fake_client = FakeLiteLLMClient()
    fake_client.stream = FakeAsyncStream(
        [
            chunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call_1",
                        "function": {"name": "search", "arguments": '{"query"'},
                    },
                    {
                        "index": 1,
                        "id": "call_2",
                        "function": {"name": "lookup", "arguments": '{"id"'},
                    },
                ]
            ),
            chunk(
                tool_calls=[
                    {"index": 1, "function": {"arguments": ': "42"}'}},
                    {"index": 0, "function": {"arguments": ': "nexus"}'}},
                ],
                finish_reason="tool_calls",
            ),
        ]
    )

    events = asyncio.run(collect_events(LiteLLMAdapter(client=fake_client)))
    completed = [
        event for event in events if isinstance(event, LLMToolCallCompletedEvent)
    ]

    assert [event.tool_call.id for event in completed] == ["call_1", "call_2"]
    assert completed[0].tool_call.arguments == {"query": "nexus"}
    assert completed[1].tool_call.arguments == {"id": "42"}


def test_malformed_final_tool_call_arguments_are_not_completed() -> None:
    fake_client = FakeLiteLLMClient()
    fake_client.stream = FakeAsyncStream(
        [
            chunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call_1",
                        "function": {"name": "search", "arguments": '{"query"'},
                    }
                ],
                finish_reason="tool_calls",
            )
        ]
    )

    events = asyncio.run(collect_events(LiteLLMAdapter(client=fake_client)))

    assert any(isinstance(event, LLMToolCallStartedEvent) for event in events)
    assert any(isinstance(event, LLMToolCallDeltaEvent) for event in events)
    assert not any(isinstance(event, LLMToolCallCompletedEvent) for event in events)
    assert_no_completed(events)
    assert events[-1] == LLMErrorEvent(
        kind=LLMUnknownProviderError.kind,
        message="LLM provider returned an invalid tool call",
        retryable=False,
    )


def test_separate_streams_do_not_share_tool_call_state() -> None:
    first_client = FakeLiteLLMClient()
    first_client.stream = FakeAsyncStream(
        [
            chunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call_1",
                        "function": {
                            "name": "search",
                            "arguments": '{"q": "one"}',
                        },
                    }
                ],
                finish_reason="tool_calls",
            )
        ]
    )
    second_client = FakeLiteLLMClient()
    second_client.stream = FakeAsyncStream(
        [
            chunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call_2",
                        "function": {
                            "name": "lookup",
                            "arguments": '{"q": "two"}',
                        },
                    }
                ],
                finish_reason="tool_calls",
            )
        ]
    )

    first_events = asyncio.run(collect_events(LiteLLMAdapter(client=first_client)))
    second_events = asyncio.run(collect_events(LiteLLMAdapter(client=second_client)))

    first_completed = next(
        event for event in first_events if isinstance(event, LLMToolCallCompletedEvent)
    )
    second_completed = next(
        event for event in second_events if isinstance(event, LLMToolCallCompletedEvent)
    )
    assert first_completed.tool_call.id == "call_1"
    assert first_completed.tool_call.arguments == {"q": "one"}
    assert second_completed.tool_call.id == "call_2"
    assert second_completed.tool_call.arguments == {"q": "two"}


@pytest.mark.parametrize(
    ("error", "expected_type"),
    [
        (AuthenticationError("secret-api-key"), LLMAuthenticationError),
        (RuntimeError("provider-secret"), LLMUnknownProviderError),
    ],
)
def test_stream_creation_failure_is_translated_safely(
    error: Exception,
    expected_type: type[LLMError],
) -> None:
    fake_client = FakeLiteLLMClient()
    fake_client.stream_error = error

    with pytest.raises(expected_type) as exc_info:
        asyncio.run(collect_events(LiteLLMAdapter(client=fake_client)))

    assert exc_info.value.message == "LLM provider request failed"
    assert str(error) not in exc_info.value.message


@pytest.mark.parametrize(
    ("error", "expected_kind", "retryable"),
    [
        (APIConnectionError("provider-secret"), LLMProviderUnavailableError.kind, True),
        (RuntimeError("provider-secret"), LLMUnknownProviderError.kind, False),
    ],
)
def test_stream_iteration_failure_yields_safe_error_event(
    error: Exception,
    expected_kind: object,
    retryable: bool,
) -> None:
    fake_client = FakeLiteLLMClient()
    stream = FakeAsyncStream(
        [chunk(content="Hel")],
        error=error,
        error_after_chunks=True,
    )
    fake_client.stream = stream

    events = asyncio.run(collect_events(LiteLLMAdapter(client=fake_client)))

    assert stream.closed is True
    assert stream.close_count == 1
    assert events == [
        LLMStartedEvent(),
        LLMTextDeltaEvent(delta="Hel"),
        LLMErrorEvent(
            kind=expected_kind,  # type: ignore[arg-type]
            message="LLM provider request failed",
            retryable=retryable,
        ),
    ]
    assert_no_completed(events)


def test_stream_cancellation_propagates_after_cleanup() -> None:
    fake_client = FakeLiteLLMClient()
    stream = CancellingAsyncStream([])
    fake_client.stream = stream

    async def consume() -> None:
        async for _event in LiteLLMAdapter(client=fake_client).stream(request()):
            pass

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(consume())

    assert stream.closed is True
    assert stream.close_count == 1


def test_normal_stream_cleanup_failure_yields_safe_error_event() -> None:
    fake_client = FakeLiteLLMClient()
    stream = FakeAsyncStream(
        [chunk(content="Hel", finish_reason="stop")],
        close_error=APIConnectionError("provider-secret"),
    )
    fake_client.stream = stream

    events = asyncio.run(collect_events(LiteLLMAdapter(client=fake_client)))

    assert stream.closed is True
    assert stream.close_count == 1
    assert events == [
        LLMStartedEvent(),
        LLMTextDeltaEvent(delta="Hel"),
        LLMErrorEvent(
            kind=LLMProviderUnavailableError.kind,
            message="LLM provider request failed",
            retryable=True,
        ),
    ]
    assert_no_completed(events)


def test_downstream_close_failure_raises_safe_error() -> None:
    fake_client = FakeLiteLLMClient()
    stream = FakeAsyncStream(
        [chunk(content="Hel")],
        close_error=APIConnectionError("provider-secret"),
    )
    fake_client.stream = stream
    adapter = LiteLLMAdapter(client=fake_client)

    async def consume_and_close() -> None:
        llm_stream = adapter.stream(request())
        first_event = await anext(llm_stream)
        assert first_event == LLMStartedEvent()
        with pytest.raises(LLMProviderUnavailableError):
            await llm_stream.aclose()

    asyncio.run(consume_and_close())

    assert stream.closed is True
    assert stream.close_count == 1


def test_stream_cleanup_does_not_mask_iteration_error() -> None:
    fake_client = FakeLiteLLMClient()
    stream = FakeAsyncStream(
        [chunk(content="Hel")],
        error=APIConnectionError("primary-provider-error"),
        error_after_chunks=True,
        close_error=RuntimeError("cleanup-secret"),
    )
    fake_client.stream = stream

    events = asyncio.run(collect_events(LiteLLMAdapter(client=fake_client)))

    assert stream.closed is True
    assert stream.close_count == 1
    assert events[-1] == LLMErrorEvent(
        kind=LLMProviderUnavailableError.kind,
        message="LLM provider request failed",
        retryable=True,
    )
    assert_no_completed(events)


def test_stream_cleanup_does_not_mask_cancellation() -> None:
    fake_client = FakeLiteLLMClient()
    stream = CancellingAsyncStream(
        [],
        close_error=RuntimeError("cleanup-secret"),
    )
    fake_client.stream = stream

    async def consume() -> None:
        async for _event in LiteLLMAdapter(client=fake_client).stream(request()):
            pass

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(consume())

    assert stream.closed is True
    assert stream.close_count == 1
