from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from nexus.llm.application import Stream
from nexus.llm.domain import (
    LLMCompletedEvent,
    LLMEvent,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMRole,
    LLMTextDeltaEvent,
)


class FakeGateway:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []
        self.response = LLMResponse(
            message=LLMMessage(role=LLMRole.ASSISTANT, content="Hello")
        )
        self.event_stream = _events()

    async def generate(self, request: LLMRequest) -> LLMResponse:
        return self.response

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        self.requests.append(request)
        return self.event_stream


async def _events() -> AsyncIterator[LLMEvent]:
    yield LLMTextDeltaEvent(delta="Hel")
    yield LLMCompletedEvent()


def test_stream_delegates_to_injected_gateway_without_wrapping_iterator() -> None:
    gateway = FakeGateway()
    request = LLMRequest(
        model="gpt-test",
        messages=[LLMMessage(role=LLMRole.USER, content="Hello")],
    )

    llm_stream = Stream(gateway=gateway).execute(request)

    assert llm_stream is gateway.event_stream

    async def collect_events() -> list[LLMEvent]:
        return [event async for event in llm_stream]

    events = asyncio.run(collect_events())

    assert gateway.requests == [request]
    assert events == [LLMTextDeltaEvent(delta="Hel"), LLMCompletedEvent()]
