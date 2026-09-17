from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest

from nexus.llm.domain import (
    LLMAuthenticationError,
    LLMCompletedEvent,
    LLMErrorEvent,
    LLMUnknownProviderError,
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


async def collect_events(adapter: LiteLLMAdapter) -> list[LLMEvent]:
    return [event async for event in adapter.stream(request())]


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
    assert events[:3] == [
        LLMStartedEvent(),
        LLMTextDeltaEvent(delta="Hel"),
        LLMTextDeltaEvent(delta="lo"),
    ]
    assert isinstance(events[3], LLMUsageEvent)
    assert events[3].usage.total_tokens == 5
    assert events[4] == LLMCompletedEvent(finish_reason=LLMFinishReason.STOP)
    assert [event.type for event in events].count(LLMEventType.STARTED) == 1
    assert [event.type for event in events].count(LLMEventType.COMPLETED) == 1


def test_stream_ignores_duplicate_finish_reason_chunks() -> None:
    fake_client = FakeLiteLLMClient()
    stream = FakeAsyncStream(
        [
            chunk(content="Hel"),
            chunk(finish_reason="stop"),
            chunk(finish_reason="stop"),
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
    assert [event.type for event in events].count(LLMEventType.COMPLETED) == 1


def test_stream_accepts_usage_only_chunks_after_finish_reason() -> None:
    fake_client = FakeLiteLLMClient()
    fake_client.stream = FakeAsyncStream(
        [
            chunk(content="Hel"),
            chunk(finish_reason="stop"),
            chunk(
                usage={
                    "prompt_tokens": 3,
                    "completion_tokens": 1,
                    "total_tokens": 4,
                },
            ),
        ]
    )

    events = asyncio.run(collect_events(LiteLLMAdapter(client=fake_client)))

    assert events == [
        LLMStartedEvent(),
        LLMTextDeltaEvent(delta="Hel"),
        LLMUsageEvent(usage=events[2].usage),  # type: ignore[union-attr]
        LLMCompletedEvent(finish_reason=LLMFinishReason.STOP),
    ]
    assert isinstance(events[2], LLMUsageEvent)
    assert events[2].usage.total_tokens == 4
    assert [event.type for event in events].count(LLMEventType.COMPLETED) == 1


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

    assert events == [
        LLMStartedEvent(),
        LLMToolCallStartedEvent(tool_call_id="call_1", name="search"),
        LLMToolCallDeltaEvent(tool_call_id="call_1", arguments_delta='{"query"'),
        LLMToolCallDeltaEvent(tool_call_id="call_1", arguments_delta=': "nexus"}'),
        LLMToolCallCompletedEvent(tool_call=events[4].tool_call),  # type: ignore[union-attr]
        LLMCompletedEvent(finish_reason=LLMFinishReason.TOOL_CALLS),
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

    assert len(completed) == 2
    assert completed[0].tool_call.id == "call_1"
    assert completed[0].tool_call.name == "search"
    assert completed[0].tool_call.arguments == {"query": "nexus"}
    assert completed[1].tool_call.id == "call_2"
    assert completed[1].tool_call.name == "lookup"
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
    assert events[-1] == LLMCompletedEvent(finish_reason=LLMFinishReason.TOOL_CALLS)


def test_separate_streams_do_not_share_tool_call_state() -> None:
    first_client = FakeLiteLLMClient()
    first_client.stream = FakeAsyncStream(
        [
            chunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call_1",
                        "function": {"name": "search", "arguments": '{"q": "one"}'},
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
                        "function": {"name": "lookup", "arguments": '{"q": "two"}'},
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


def test_stream_creation_provider_failure_is_translated_safely() -> None:
    fake_client = FakeLiteLLMClient()
    fake_client.stream_error = AuthenticationError("secret-api-key")

    with pytest.raises(LLMAuthenticationError) as exc_info:
        asyncio.run(collect_events(LiteLLMAdapter(client=fake_client)))

    assert exc_info.value.message == "LLM provider request failed"
    assert "secret-api-key" not in exc_info.value.message


def test_stream_creation_unclassified_provider_failure_is_translated_safely() -> None:
    fake_client = FakeLiteLLMClient()
    fake_client.stream_error = RuntimeError("provider-secret")

    with pytest.raises(LLMUnknownProviderError) as exc_info:
        asyncio.run(collect_events(LiteLLMAdapter(client=fake_client)))

    assert exc_info.value.message == "LLM provider request failed"
    assert "provider-secret" not in exc_info.value.message


def test_stream_iteration_provider_failure_yields_safe_error_event_and_closes() -> None:
    fake_client = FakeLiteLLMClient()
    stream = FakeAsyncStream(
        [chunk(content="Hel")],
        error=APIConnectionError("provider-secret"),
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
            kind=LLMProviderUnavailableError.kind,
            message="LLM provider request failed",
            retryable=True,
        ),
    ]
    assert not any(event.type is LLMEventType.COMPLETED for event in events)


def test_stream_iteration_unclassified_exception_yields_safe_error_event() -> None:
    fake_client = FakeLiteLLMClient()
    stream = FakeAsyncStream(
        [chunk(content="Hel")],
        error=RuntimeError("provider-secret"),
        error_after_chunks=True,
    )
    fake_client.stream = stream

    events = asyncio.run(collect_events(LiteLLMAdapter(client=fake_client)))

    assert events == [
        LLMStartedEvent(),
        LLMTextDeltaEvent(delta="Hel"),
        LLMErrorEvent(
            kind=LLMUnknownProviderError.kind,
            message="LLM provider request failed",
            retryable=False,
        ),
    ]
    assert stream.close_count == 1
    assert not any(event.type is LLMEventType.COMPLETED for event in events)


def test_early_consumer_close_closes_upstream_stream() -> None:
    fake_client = FakeLiteLLMClient()
    stream = FakeAsyncStream([chunk(content="Hel"), chunk(content="lo")])
    fake_client.stream = stream
    llm_stream = LiteLLMAdapter(client=fake_client).stream(request())

    async def consume_one_event_then_close() -> None:
        first_event = await anext(llm_stream)
        assert first_event == LLMStartedEvent()
        await llm_stream.aclose()

    asyncio.run(consume_one_event_then_close())

    assert stream.closed is True
    assert stream.close_count == 1
    assert stream._index == 0


def test_explicit_downstream_close_cleanup_failure_raises_nexus_error() -> None:
    fake_client = FakeLiteLLMClient()
    stream = FakeAsyncStream(
        [chunk(content="Hel")],
        close_error=RuntimeError("cleanup-secret"),
    )
    fake_client.stream = stream
    llm_stream = LiteLLMAdapter(client=fake_client).stream(request())

    async def consume_one_event_then_close() -> None:
        first_event = await anext(llm_stream)
        assert first_event == LLMStartedEvent()
        await llm_stream.aclose()

    with pytest.raises(LLMUnknownProviderError) as exc_info:
        asyncio.run(consume_one_event_then_close())

    assert stream.close_count == 1
    assert exc_info.value.message == "LLM provider request failed"
    assert "cleanup-secret" not in exc_info.value.message


def test_cancellation_closes_upstream_and_propagates() -> None:
    fake_client = FakeLiteLLMClient()
    stream = CancellingAsyncStream([])
    fake_client.stream = stream

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(collect_events(LiteLLMAdapter(client=fake_client)))

    assert stream.closed is True
    assert stream.close_count == 1


def test_provider_error_remains_primary_when_cleanup_also_fails() -> None:
    fake_client = FakeLiteLLMClient()
    stream = FakeAsyncStream(
        [chunk(content="Hel")],
        error=APIConnectionError("provider-secret"),
        error_after_chunks=True,
        close_error=APIConnectionError("cleanup-secret"),
    )
    fake_client.stream = stream

    events = asyncio.run(collect_events(LiteLLMAdapter(client=fake_client)))

    assert stream.close_count == 1
    assert events[-1] == LLMErrorEvent(
        kind=LLMProviderUnavailableError.kind,
        message="LLM provider request failed",
        retryable=True,
    )
    assert "cleanup-secret" not in events[-1].message
    assert not any(event.type is LLMEventType.COMPLETED for event in events)


def test_cancellation_remains_primary_when_cleanup_also_fails() -> None:
    fake_client = FakeLiteLLMClient()
    stream = CancellingAsyncStream(
        [],
        close_error=APIConnectionError("cleanup-secret"),
    )
    fake_client.stream = stream

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(collect_events(LiteLLMAdapter(client=fake_client)))

    assert stream.close_count == 1


def test_cleanup_only_failure_becomes_safe_nexus_error_without_completion() -> None:
    fake_client = FakeLiteLLMClient()
    stream = FakeAsyncStream(
        [chunk(content="Hel")],
        close_error=APIConnectionError("cleanup-secret"),
    )
    fake_client.stream = stream

    with pytest.raises(LLMProviderUnavailableError) as exc_info:
        asyncio.run(collect_events(LiteLLMAdapter(client=fake_client)))

    assert stream.close_count == 1
    assert exc_info.value.message == "LLM provider request failed"
    assert "cleanup-secret" not in exc_info.value.message


def test_normal_post_start_cleanup_failure_yields_error_event_without_completion() -> None:
    fake_client = FakeLiteLLMClient()
    stream = FakeAsyncStream(
        [chunk(content="Hel")],
        close_error=RuntimeError("cleanup-secret"),
    )
    fake_client.stream = stream

    events = asyncio.run(collect_events(LiteLLMAdapter(client=fake_client)))

    assert stream.close_count == 1
    assert events == [
        LLMStartedEvent(),
        LLMTextDeltaEvent(delta="Hel"),
        LLMErrorEvent(
            kind=LLMUnknownProviderError.kind,
            message="LLM provider request failed",
            retryable=False,
        ),
    ]
    assert not any(event.type is LLMEventType.COMPLETED for event in events)
