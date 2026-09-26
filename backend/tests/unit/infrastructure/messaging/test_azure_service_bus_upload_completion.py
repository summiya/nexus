from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Self, cast

import pytest
from azure.servicebus import ServiceBusReceivedMessage
from azure.servicebus.amqp import AmqpMessageBodyType
from azure.servicebus.exceptions import ServiceBusError

from nexus.files.ports import UploadCompletionEvent
from nexus.infrastructure.messaging import (
    azure_service_bus_upload_completion as worker_module,
)
from nexus.infrastructure.messaging.azure_service_bus_upload_completion import (
    MAX_UPLOAD_COMPLETION_MESSAGE_BODY_BYTES,
    AzureServiceBusUploadCompletionWorker,
    InvalidUploadCompletionMessageBody,
    decode_upload_completion_body,
)
from nexus.infrastructure.storage import AzureBlobCreatedEventMapper

AZURE_SOURCE = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/"
    "resourceGroups/nexus/providers/Microsoft.Storage/storageAccounts/nexus"
)
STORAGE_KEY = "files/0123456789abcdef0123456789abcdef"


class FakeMessage:
    def __init__(
        self,
        body: object,
        *,
        body_type: AmqpMessageBodyType = AmqpMessageBodyType.DATA,
        message_id: str = "service-bus-message-1",
    ) -> None:
        self.body = body
        self.body_type = body_type
        self.message_id = message_id


class FakeReceiver:
    def __init__(
        self,
        batches: list[list[FakeMessage]] | None = None,
        *,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        self.batches = list(batches or [])
        self.stop_event = stop_event
        self.complete_calls: list[FakeMessage] = []
        self.abandon_calls: list[FakeMessage] = []
        self.dead_letter_calls: list[tuple[FakeMessage, str, str]] = []
        self.receive_calls: list[tuple[int | None, float | None]] = []
        self.complete_error: BaseException | None = None
        self.abandon_error: BaseException | None = None
        self.dead_letter_error: BaseException | None = None
        self.enter_calls = 0
        self.exit_calls = 0

    async def __aenter__(self) -> Self:
        self.enter_calls += 1
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.exit_calls += 1

    async def receive_messages(
        self,
        *,
        max_message_count: int | None = 1,
        max_wait_time: float | None = None,
    ) -> list[FakeMessage]:
        self.receive_calls.append((max_message_count, max_wait_time))
        if self.batches:
            return self.batches.pop(0)
        if self.stop_event is not None:
            self.stop_event.set()
        return []

    async def complete_message(self, message: FakeMessage) -> None:
        if self.complete_error is not None:
            raise self.complete_error
        self.complete_calls.append(message)

    async def abandon_message(self, message: FakeMessage) -> None:
        if self.abandon_error is not None:
            raise self.abandon_error
        self.abandon_calls.append(message)

    async def dead_letter_message(
        self,
        message: FakeMessage,
        *,
        reason: str,
        error_description: str,
    ) -> None:
        if self.dead_letter_error is not None:
            raise self.dead_letter_error
        self.dead_letter_calls.append((message, reason, error_description))


class FakeClient:
    def __init__(self, receiver: FakeReceiver) -> None:
        self.receiver = receiver
        self.receiver_kwargs: list[dict[str, object]] = []

    def get_queue_receiver(self, **kwargs: object) -> FakeReceiver:
        self.receiver_kwargs.append(dict(kwargs))
        return self.receiver


class RecordingHandler:
    def __init__(self, outcomes: list[BaseException | None] | None = None) -> None:
        self.outcomes = list(outcomes or [])
        self.events: list[UploadCompletionEvent] = []

    async def handle(self, event: UploadCompletionEvent) -> None:
        self.events.append(event)
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if outcome is not None:
                raise outcome


class BlockingHandler:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    async def handle(self, event: UploadCompletionEvent) -> None:
        del event
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def _mapper() -> AzureBlobCreatedEventMapper:
    return AzureBlobCreatedEventMapper(
        expected_source=AZURE_SOURCE,
        expected_container="nexus-files",
        nexus_source="azure-primary",
    )


def _payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "specversion": "1.0",
        "type": "Microsoft.Storage.BlobCreated",
        "source": AZURE_SOURCE,
        "id": "event-1",
        "time": "2026-09-26T00:00:00Z",
        "subject": f"/blobServices/default/containers/nexus-files/blobs/{STORAGE_KEY}",
        "data": {
            "api": "PutBlob",
            "blobType": "BlockBlob",
            "eTag": "0x8D123",
            "contentLength": 42,
        },
    }
    payload.update(changes)
    return payload


def _message(payload: Mapping[str, object] | None = None) -> FakeMessage:
    encoded = json.dumps(payload or _payload()).encode("utf-8")
    return FakeMessage((encoded,))


def _worker(
    receiver: FakeReceiver,
    handler: RecordingHandler | BlockingHandler,
    *,
    jitter: Any | None = None,
) -> AzureServiceBusUploadCompletionWorker:
    values: dict[str, object] = {}
    if jitter is not None:
        values["jitter"] = jitter
    return AzureServiceBusUploadCompletionWorker(
        client=cast(Any, FakeClient(receiver)),
        queue_name="file-upload-completions",
        mapper=_mapper(),
        handler=handler,
        auto_lock_renewer=cast(Any, object()),
        **values,  # type: ignore[arg-type]
    )


def _json_body_with_exact_size(size: int) -> bytes:
    prefix = b'{"value":"'
    suffix = b'"}'
    assert size >= len(prefix) + len(suffix)
    return prefix + (b"a" * (size - len(prefix) - len(suffix))) + suffix


def test_body_limit_is_exactly_64_kib() -> None:
    assert MAX_UPLOAD_COMPLETION_MESSAGE_BODY_BYTES == 65_536

    accepted = FakeMessage(
        (_json_body_with_exact_size(MAX_UPLOAD_COMPLETION_MESSAGE_BODY_BYTES),)
    )
    assert decode_upload_completion_body(cast(Any, accepted))["value"]

    rejected = FakeMessage(
        (_json_body_with_exact_size(MAX_UPLOAD_COMPLETION_MESSAGE_BODY_BYTES + 1),)
    )
    with pytest.raises(InvalidUploadCompletionMessageBody):
        decode_upload_completion_body(cast(Any, rejected))


def test_body_limit_applies_across_ordered_data_sections() -> None:
    body = _json_body_with_exact_size(MAX_UPLOAD_COMPLETION_MESSAGE_BODY_BYTES)
    split = len(body) // 2
    message = FakeMessage((body[:split], body[split:]))

    assert decode_upload_completion_body(cast(Any, message))["value"]


@pytest.mark.parametrize(
    "message",
    [
        FakeMessage((), body_type=AmqpMessageBodyType.DATA),
        FakeMessage((b"\xff",), body_type=AmqpMessageBodyType.DATA),
        FakeMessage((b"not-json",), body_type=AmqpMessageBodyType.DATA),
        FakeMessage((b"[]",), body_type=AmqpMessageBodyType.DATA),
        FakeMessage((b"null",), body_type=AmqpMessageBodyType.DATA),
        FakeMessage((["not-bytes"],), body_type=AmqpMessageBodyType.DATA),
        FakeMessage(b"{}", body_type=AmqpMessageBodyType.VALUE),
        FakeMessage([[1]], body_type=AmqpMessageBodyType.SEQUENCE),
    ],
)
def test_decoder_rejects_unsupported_or_malformed_bodies(
    message: FakeMessage,
) -> None:
    with pytest.raises(
        InvalidUploadCompletionMessageBody,
        match="The message body is not a valid upload event",
    ):
        decode_upload_completion_body(cast(Any, message))


def test_valid_event_is_dispatched_then_completed() -> None:
    async def scenario() -> None:
        receiver = FakeReceiver()
        handler = RecordingHandler()
        message = _message()

        await _worker(receiver, handler)._process_message(
            cast(Any, receiver),
            cast(ServiceBusReceivedMessage, message),
            asyncio.Event(),
        )

        assert len(handler.events) == 1
        assert handler.events[0].event_id == "event-1"
        assert receiver.complete_calls == [message]
        assert receiver.abandon_calls == []

    asyncio.run(scenario())


def test_invalid_body_and_mapper_failure_use_bounded_dead_letter_reasons() -> None:
    async def scenario() -> None:
        receiver = FakeReceiver()
        handler = RecordingHandler()
        worker = _worker(receiver, handler)

        invalid_body = FakeMessage((b"secret-not-json",))
        await worker._process_message(
            cast(Any, receiver),
            cast(ServiceBusReceivedMessage, invalid_body),
            asyncio.Event(),
        )
        invalid_event = _message(_payload(type="Microsoft.Storage.BlobDeleted"))
        await worker._process_message(
            cast(Any, receiver),
            cast(ServiceBusReceivedMessage, invalid_event),
            asyncio.Event(),
        )

        assert [call[1] for call in receiver.dead_letter_calls] == [
            "INVALID_MESSAGE_BODY",
            "INVALID_BLOB_CREATED_EVENT",
        ]
        descriptions = [call[2] for call in receiver.dead_letter_calls]
        assert descriptions == [
            "The message body is not a valid upload event.",
            "The BlobCreated event is invalid.",
        ]
        assert "secret-not-json" not in repr(receiver.dead_letter_calls)
        assert handler.events == []

    asyncio.run(scenario())


def test_handler_failure_is_abandoned_once_without_same_delivery_retry() -> None:
    async def scenario() -> None:
        receiver = FakeReceiver()
        handler = RecordingHandler([RuntimeError("sensitive dependency failure")])
        message = _message()

        await _worker(receiver, handler)._process_message(
            cast(Any, receiver),
            cast(ServiceBusReceivedMessage, message),
            asyncio.Event(),
        )

        assert len(handler.events) == 1
        assert receiver.abandon_calls == [message]
        assert receiver.complete_calls == []

    asyncio.run(scenario())


def test_graceful_shutdown_cancels_and_abandons_in_flight_without_jitter() -> None:
    async def scenario() -> None:
        receiver = FakeReceiver([[_message()]])
        handler = BlockingHandler()
        jitter_calls: list[tuple[float, float]] = []
        worker = _worker(
            receiver,
            handler,
            jitter=lambda minimum, maximum: (
                jitter_calls.append((minimum, maximum)) or minimum
            ),
        )
        stop_event = asyncio.Event()

        processing = asyncio.create_task(worker.run(stop_event))
        await handler.started.wait()
        stop_event.set()
        await processing

        assert handler.cancelled is True
        assert len(receiver.abandon_calls) == 1
        assert receiver.complete_calls == []
        assert jitter_calls == []

    asyncio.run(scenario())


def test_receive_loop_applies_half_to_full_exponential_failure_delay_and_resets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        messages = [[_message()] for _ in range(4)]
        receiver = FakeReceiver(messages, stop_event=stop_event)
        handler = RecordingHandler(
            [RuntimeError("one"), RuntimeError("two"), None, RuntimeError("three")]
        )
        jitter_bounds: list[tuple[float, float]] = []
        delays: list[float] = []

        def below_minimum(minimum: float, maximum: float) -> float:
            jitter_bounds.append((minimum, maximum))
            return 0.0

        async def record_wait(_stop: asyncio.Event, delay: float) -> bool:
            delays.append(delay)
            return False

        monkeypatch.setattr(worker_module, "_wait_for_stop", record_wait)
        worker = _worker(receiver, handler, jitter=below_minimum)

        await worker.run(stop_event)

        assert delays == [1.0, 2.0, 1.0]
        assert jitter_bounds == [(1.0, 2.0), (2.0, 4.0), (1.0, 2.0)]
        assert len(receiver.abandon_calls) == 3
        assert len(receiver.complete_calls) == 1
        client = cast(FakeClient, worker.client)
        assert client.receiver_kwargs[0]["prefetch_count"] == 0
        assert str(client.receiver_kwargs[0]["receive_mode"]).endswith("PEEK_LOCK")
        assert client.receiver_kwargs[0]["auto_lock_renewer"] is (
            worker.auto_lock_renewer
        )
        assert all(call[0] == 1 for call in receiver.receive_calls)

    asyncio.run(scenario())


def test_failure_delay_doubles_to_sixty_second_cap() -> None:
    worker = _worker(
        FakeReceiver(),
        RecordingHandler(),
        jitter=lambda minimum, _maximum: minimum,
    )

    assert [worker._failure_delay(count) for count in range(1, 8)] == [
        1.0,
        2.0,
        4.0,
        8.0,
        16.0,
        30.0,
        30.0,
    ]


def test_settlement_failures_are_not_reported_as_success() -> None:
    async def scenario() -> None:
        receiver = FakeReceiver()
        receiver.complete_error = ServiceBusError("complete failed")
        handler = RecordingHandler()

        await _worker(receiver, handler)._process_message(
            cast(Any, receiver),
            cast(ServiceBusReceivedMessage, _message()),
            asyncio.Event(),
        )

        assert len(handler.events) == 1
        assert receiver.complete_calls == []

    asyncio.run(scenario())


def test_event_correlation_does_not_use_service_bus_message_id() -> None:
    event = UploadCompletionEvent(
        event_id="cloud-event-id",
        source="azure-primary",
        storage_key=STORAGE_KEY,
        occurred_at=datetime(2026, 9, 26, tzinfo=UTC),
        entity_tag="etag",
        reported_size_bytes=1,
    )

    first = worker_module._safe_event_correlation(event)
    second = worker_module._safe_event_correlation(event)

    assert first == second
    assert "cloud-event-id" not in first
