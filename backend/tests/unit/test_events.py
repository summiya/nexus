import asyncio
import inspect
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from nexus.events import (
    EventEnvelope,
    EventPublisher,
    EventType,
    InProcessEventPublisher,
)

EXPECTED_EVENT_TYPES = {
    "conversation.created",
    "message.created",
    "run.started",
    "run.completed",
    "run.failed",
    "run.cancelled",
    "model.request.started",
    "model.request.completed",
    "tool.started",
    "tool.completed",
}


def make_event(event_type: EventType = EventType.RUN_STARTED) -> EventEnvelope:
    return EventEnvelope.create(
        event_type=event_type,
        request_id="req_123",
        data={"run_id": "run_123"},
    )


def test_event_types_match_canonical_contract() -> None:
    assert {event_type.value for event_type in EventType} == EXPECTED_EVENT_TYPES


def test_event_create_populates_required_fields() -> None:
    before = datetime.now(UTC)
    event = make_event()
    after = datetime.now(UTC)

    assert event.event_id.startswith("evt_")
    assert event.event_type is EventType.RUN_STARTED
    assert event.version == 1
    assert before <= event.timestamp <= after
    assert event.timestamp.tzinfo is not None
    assert event.timestamp.utcoffset() == UTC.utcoffset(event.timestamp)
    assert event.request_id == "req_123"
    assert event.data == {"run_id": "run_123"}


def test_event_envelope_validates_required_fields() -> None:
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate({})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_id", ""),
        ("request_id", ""),
        ("version", 0),
        ("event_type", "unknown.event"),
    ],
)
def test_event_envelope_rejects_invalid_required_values(field: str, value: object) -> None:
    payload = {
        "event_id": "evt_123",
        "event_type": EventType.RUN_STARTED,
        "version": 1,
        "timestamp": datetime.now(UTC),
        "request_id": "req_123",
        "data": {},
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(payload)


def test_event_envelope_is_immutable() -> None:
    event = make_event()

    with pytest.raises(ValidationError):
        event.version = 2  # type: ignore[misc]


def test_event_publisher_contract_is_async() -> None:
    assert inspect.iscoroutinefunction(EventPublisher.publish)


def test_publish_with_no_handlers_succeeds() -> None:
    publisher = InProcessEventPublisher()

    asyncio.run(publisher.publish(make_event()))


def test_matching_handler_receives_exact_event() -> None:
    publisher = InProcessEventPublisher()
    event = make_event()
    received: list[EventEnvelope] = []

    async def handler(published_event: EventEnvelope) -> None:
        received.append(published_event)

    publisher.subscribe(EventType.RUN_STARTED, handler)
    asyncio.run(publisher.publish(event))

    assert received == [event]
    assert received[0] is event


def test_only_matching_handlers_are_called() -> None:
    publisher = InProcessEventPublisher()
    calls: list[str] = []

    async def run_handler(_event: EventEnvelope) -> None:
        calls.append("run")

    async def tool_handler(_event: EventEnvelope) -> None:
        calls.append("tool")

    publisher.subscribe(EventType.RUN_STARTED, run_handler)
    publisher.subscribe(EventType.TOOL_STARTED, tool_handler)

    asyncio.run(publisher.publish(make_event(EventType.RUN_STARTED)))

    assert calls == ["run"]


def test_handlers_are_awaited_in_registration_order() -> None:
    publisher = InProcessEventPublisher()
    calls: list[str] = []

    async def first(_event: EventEnvelope) -> None:
        await asyncio.sleep(0)
        calls.append("first")

    async def second(_event: EventEnvelope) -> None:
        calls.append("second")

    publisher.subscribe(EventType.RUN_STARTED, first)
    publisher.subscribe(EventType.RUN_STARTED, second)

    asyncio.run(publisher.publish(make_event()))

    assert calls == ["first", "second"]


def test_handler_failure_propagates_and_stops_dispatch() -> None:
    publisher = InProcessEventPublisher()
    calls: list[str] = []

    async def failing(_event: EventEnvelope) -> None:
        calls.append("failing")
        raise RuntimeError("publisher failure")

    async def later(_event: EventEnvelope) -> None:
        calls.append("later")

    publisher.subscribe(EventType.RUN_STARTED, failing)
    publisher.subscribe(EventType.RUN_STARTED, later)

    with pytest.raises(RuntimeError, match="publisher failure"):
        asyncio.run(publisher.publish(make_event()))

    assert calls == ["failing"]


def test_failed_handler_is_not_retried() -> None:
    publisher = InProcessEventPublisher()
    attempts = 0

    async def failing(_event: EventEnvelope) -> None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("publisher failure")

    publisher.subscribe(EventType.RUN_STARTED, failing)

    with pytest.raises(RuntimeError):
        asyncio.run(publisher.publish(make_event()))

    assert attempts == 1
