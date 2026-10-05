import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from azure.servicebus.amqp import AmqpMessageBodyType
from azure.servicebus.exceptions import (
    MessageLockLostError,
    ServiceBusAuthenticationError,
    ServiceBusError,
)

from nexus.documents.ports.processing import (
    DocumentProcessingRequested,
    ProcessingRequestRejected,
)
from nexus.infrastructure.messaging.azure_service_bus_document_processing import (
    AzureServiceBusDocumentPublisher,
    AzureServiceBusDocumentWorker,
    decode_document_message,
    encode_document_message,
)


def event():
    return DocumentProcessingRequested(uuid4(), uuid4(), uuid4())


def delivery(body=None):
    return SimpleNamespace(
        body=body if body is not None else [encode_document_message(event())],
        body_type=AmqpMessageBodyType.DATA,
        message_id="private-id",
    )


def worker(handler=None, client=None, concurrency=2):
    return AzureServiceBusDocumentWorker(
        client=client or MagicMock(),
        queue_name="documents",
        handler=handler or AsyncMock(),
        auto_lock_renewer=MagicMock(),
        concurrency=concurrency,
    )


def test_roundtrip_and_deterministic():
    request = event()
    encoded = encode_document_message(request)
    assert encoded == encode_document_message(request)
    assert len(encoded) < 65_536
    assert decode_document_message(delivery([encoded[:10], encoded[10:]])) == request
    assert len(json.loads(encoded)) == 4


@pytest.mark.parametrize(
    "body",
    [
        [],
        [b"{}"],
        [b"[]"],
        [b"\xff"],
        [b" " * 65_537],
        [b'{"schema_version":1,"schema_version":1}'],
        ["text"],
        [b"{"],
        [b"[" * 2000],
    ],
)
def test_invalid_body(body):
    with pytest.raises((ValueError, TypeError)):
        decode_document_message(delivery(body))


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": True},
        {"schema_version": 2},
        {"request_public_id": 42},
        {"document_public_id": "00000000-0000-0000-0000-000000000000"},
        {"extra": "private"},
    ],
)
def test_invalid_contract(change):
    payload = json.loads(encode_document_message(event()))
    payload.update(change)
    with pytest.raises(ValueError):
        decode_document_message(delivery([json.dumps(payload).encode()]))


@pytest.mark.parametrize(
    "failure,action",
    [
        (None, "complete_message"),
        (ProcessingRequestRejected(), "dead_letter_message"),
        (RuntimeError("private"), "abandon_message"),
    ],
)
def test_settlement(failure, action):
    async def run():
        receiver, handler = AsyncMock(), AsyncMock()
        handler.execute.side_effect = failure
        await worker(handler).handle_delivery(receiver, delivery(), asyncio.Event())
        getattr(receiver, action).assert_awaited_once()
        for other in {"complete_message", "dead_letter_message", "abandon_message"} - {
            action
        }:
            getattr(receiver, other).assert_not_awaited()

    asyncio.run(run())


def test_bad_payload_deadletters_fixed_description_without_call():
    async def run():
        receiver, handler = AsyncMock(), AsyncMock()
        await worker(handler).handle_delivery(
            receiver, delivery([b"private"]), asyncio.Event()
        )
        handler.execute.assert_not_awaited()
        assert receiver.dead_letter_message.await_args.kwargs == {
            "reason": "INVALID_DOCUMENT_PROCESSING_REQUEST",
            "error_description": "The document processing request is invalid.",
        }

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True])
def test_shutdown_abandons_after_handler_cancellation(cancel):
    async def run():
        entered, settled = asyncio.Event(), asyncio.Event()

        class Handler:
            async def execute(self, request):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    settled.set()

        receiver, stop = AsyncMock(), asyncio.Event()
        task = asyncio.create_task(
            worker(Handler()).handle_delivery(receiver, delivery(), stop)
        )
        await entered.wait()
        if cancel:
            task.cancel()
        else:
            stop.set()
        await asyncio.gather(task, return_exceptions=True)
        assert settled.is_set()
        receiver.abandon_message.assert_awaited_once()
        receiver.complete_message.assert_not_awaited()

    asyncio.run(run())


def test_send_stable_message_id():
    async def run():
        client = MagicMock()
        sender = AsyncMock()
        client.get_queue_sender.return_value.__aenter__.return_value = sender
        request = event()
        publisher = AzureServiceBusDocumentPublisher(client, "documents")
        await publisher.publish(request)
        await publisher.publish(request)
        assert [
            call.args[0].message_id for call in sender.send_messages.await_args_list
        ] == [str(request.request_public_id)] * 2

    asyncio.run(run())


def test_receive_slots_bounded_and_fatal_auth():
    async def run():
        client, receiver, stop = MagicMock(), AsyncMock(), asyncio.Event()
        client.get_queue_receiver.return_value = receiver
        entered = 0
        ready = asyncio.Event()

        async def receive(**kwargs):
            nonlocal entered
            assert kwargs["max_message_count"] == 1
            entered += 1
            if entered == 3:
                ready.set()
            await stop.wait()
            return []

        receiver.receive_messages.side_effect = receive
        task = asyncio.create_task(worker(client=client, concurrency=3).run(stop))
        await asyncio.wait_for(ready.wait(), 1)
        assert client.get_queue_receiver.call_count == 3
        assert all(
            call.kwargs["prefetch_count"] == 0
            for call in client.get_queue_receiver.call_args_list
        )
        stop.set()
        await task
        receiver.receive_messages.side_effect = ServiceBusAuthenticationError(
            message="private"
        )
        with pytest.raises(ExceptionGroup):
            await worker(client=client, concurrency=1).run(asyncio.Event())

    asyncio.run(run())


def test_settlement_failure_does_not_escape():
    async def run():
        receiver = AsyncMock()
        receiver.complete_message.side_effect = ServiceBusError("private")
        await worker().handle_delivery(receiver, delivery(), asyncio.Event())

    asyncio.run(run())


@pytest.mark.parametrize(
    "failure", [ServiceBusError("private"), MessageLockLostError(message="private")]
)
def test_recoverable_receive_reopens_link(monkeypatch, failure):
    async def run():
        client, receiver, stop = MagicMock(), AsyncMock(), asyncio.Event()
        client.get_queue_receiver.return_value = receiver

        async def finish(**kwargs):
            stop.set()
            return []

        calls = 0

        async def receive(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise failure
            return await finish(**kwargs)

        receiver.receive_messages.side_effect = receive
        pause = AsyncMock()
        monkeypatch.setattr(
            "nexus.infrastructure.messaging.azure_service_bus_document_processing._wait_for_stop",
            pause,
        )
        await worker(client=client, concurrency=1).run(stop)
        assert client.get_queue_receiver.call_count == 2
        pause.assert_awaited_once()

    asyncio.run(run())


def test_fatal_sender_maps_to_provider_neutral_error():
    from nexus.documents.ports.dispatch import DocumentPublicationError

    async def run():
        client = MagicMock()
        sender = AsyncMock()
        client.get_queue_sender.return_value.__aenter__.return_value = sender
        sender.send_messages.side_effect = ServiceBusAuthenticationError(
            message="private"
        )
        with pytest.raises(DocumentPublicationError, match="configuration failed"):
            await AzureServiceBusDocumentPublisher(client, "documents").publish(event())

    asyncio.run(run())


def test_error_logs_do_not_expose_payload_or_exception_text(monkeypatch):
    from unittest.mock import Mock

    async def run():
        safe_logger = Mock()
        monkeypatch.setattr(
            "nexus.infrastructure.messaging.azure_service_bus_document_processing.logger",
            safe_logger,
        )
        handler = AsyncMock()
        handler.execute.side_effect = RuntimeError("private-content-and-credentials")
        await worker(handler).handle_delivery(AsyncMock(), delivery(), asyncio.Event())
        log = safe_logger.warning.call_args
        assert log.args == ("document_handler_failed",)
        assert log.kwargs["error_type"] == "RuntimeError"
        assert len(log.kwargs["correlation"]) == 16
        assert "private" not in str(log)

    asyncio.run(run())
