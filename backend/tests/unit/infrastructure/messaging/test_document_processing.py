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
    ProcessingOutcome,
    ProcessingRequestRejected,
    ProcessingResult,
)
from nexus.infrastructure.messaging.azure_service_bus_document_processing import (
    AzureServiceBusDocumentPublisher,
    AzureServiceBusDocumentWorker,
    decode_document_message,
    encode_document_message,
)
from nexus.infrastructure.messaging.azure_service_bus_publisher import (
    AzureServiceBusPublicationError,
    AzureServiceBusQueuePublisher,
)


def event():
    return DocumentProcessingRequested(uuid4(), uuid4(), uuid4())


def delivery(body=None):
    return SimpleNamespace(
        body=body if body is not None else [encode_document_message(event())],
        body_type=AmqpMessageBodyType.DATA,
        message_id="private-id",
        delivery_count=0,
    )


def worker(handler=None, client=None, concurrency=2):
    return AzureServiceBusDocumentWorker(
        client=client or MagicMock(),
        queue_name="documents",
        handler=handler
        or AsyncMock(
            execute=AsyncMock(return_value=ProcessingResult(ProcessingOutcome.SUCCESS))
        ),
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
        handler.execute.return_value = ProcessingResult(ProcessingOutcome.SUCCESS)
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
            async def execute(self, request, *, final_attempt=False):
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
        transport = AsyncMock()
        request = event()
        publisher = AzureServiceBusDocumentPublisher(transport, "documents")
        await publisher.publish(request)
        await publisher.publish(request)
        assert transport.publish.await_count == 2
        for call in transport.publish.await_args_list:
            assert call.kwargs == {
                "queue_name": "documents",
                "body": encode_document_message(request),
                "message_id": str(request.request_public_id),
                "content_type": "application/json",
            }

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

        receiver.peek_messages.return_value = []
        receiver.receive_messages.side_effect = receive
        task = asyncio.create_task(worker(client=client, concurrency=3).run(stop))
        await asyncio.wait_for(ready.wait(), 1)
        assert client.get_queue_receiver.call_count == 4
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

        receiver.peek_messages.return_value = []
        receiver.receive_messages.side_effect = receive
        pause = AsyncMock()
        monkeypatch.setattr(
            "nexus.infrastructure.messaging.azure_service_bus_document_processing._wait_for_stop",
            pause,
        )
        await worker(client=client, concurrency=1).run(stop)
        assert (
            sum(
                "sub_queue" not in c.kwargs
                for c in client.get_queue_receiver.call_args_list
            )
            == 2
        )
        assert pause.await_count >= 1

    asyncio.run(run())


def test_fatal_sender_maps_to_provider_neutral_error():
    from nexus.documents.ports.dispatch import DocumentPublicationError

    async def run():
        transport = AsyncMock()
        original = AzureServiceBusPublicationError()
        transport.publish.side_effect = original
        with pytest.raises(
            DocumentPublicationError, match="configuration failed"
        ) as exc:
            await AzureServiceBusDocumentPublisher(transport, "documents").publish(
                event()
            )
        assert exc.value.__cause__ is original

    asyncio.run(run())


@pytest.mark.parametrize("outcome", ["success", "transient", "fatal"])
def test_document_publication_preserves_dispatch_outcomes(outcome):
    from nexus.documents.application.dispatch_processing import (
        DispatchDocumentProcessing,
    )
    from nexus.documents.ports.dispatch import DispatchLease, DocumentPublicationError

    async def run():
        client, sender, store = MagicMock(), AsyncMock(), AsyncMock()
        client.close = AsyncMock()
        client.get_queue_sender.return_value.__aenter__.return_value = sender
        request = event()
        lease = DispatchLease(request, uuid4(), 1)
        store.claim.return_value = [lease]
        original = None
        if outcome != "success":
            error = (
                ServiceBusAuthenticationError if outcome == "fatal" else ServiceBusError
            )
            original = error(message="private")
            sender.send_messages.side_effect = original
        dispatcher = DispatchDocumentProcessing(
            persistence=store,
            publisher=AzureServiceBusDocumentPublisher(
                AzureServiceBusQueuePublisher(client), "documents"
            ),
        )
        if outcome == "fatal":
            with pytest.raises(ExceptionGroup) as exc:
                await dispatcher.run(asyncio.Event())
            error = exc.value.exceptions[0]
            assert isinstance(error, DocumentPublicationError)
            assert isinstance(error.__cause__, AzureServiceBusPublicationError)
            assert error.__cause__.__cause__ is original
            store.retry.assert_not_awaited()
            store.acknowledge.assert_not_awaited()
        else:
            assert await dispatcher.dispatch_once() == 1
            if outcome == "success":
                store.acknowledge.assert_awaited_once_with(lease)
                store.retry.assert_not_awaited()
            else:
                store.retry.assert_awaited_once_with(lease, delay_seconds=2)
                store.acknowledge.assert_not_awaited()
        sent = sender.send_messages.await_args.args[0]
        assert sent.message_id == str(request.request_public_id)
        assert sent.content_type == "application/json"
        assert b"".join(sent.body) == encode_document_message(request)
        client.close.assert_not_called()

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


@pytest.mark.parametrize("count,final", [(0, False), (8, False), (9, True), (15, True)])
def test_zero_based_delivery_budget(count, final):
    async def run():
        handler, receiver = AsyncMock(), AsyncMock()
        handler.execute.return_value = ProcessingResult(ProcessingOutcome.RETRYABLE)
        message = delivery()
        message.delivery_count = count
        await worker(handler).handle_delivery(receiver, message, asyncio.Event())
        assert handler.execute.await_args.kwargs == {"final_attempt": final}
        receiver.abandon_message.assert_awaited_once()
        receiver.dead_letter_message.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("count", [None, True, -1, "0", 0.0])
def test_invalid_delivery_metadata_never_claims(count):
    async def run():
        handler, receiver = AsyncMock(), AsyncMock()
        message = delivery()
        message.delivery_count = count
        await worker(handler).handle_delivery(receiver, message, asyncio.Event())
        handler.execute.assert_not_awaited()
        receiver.abandon_message.assert_awaited_once()

    asyncio.run(run())


def test_terminal_finalized_uses_only_safe_metadata():
    from nexus.documents.domain import DocumentFailure

    async def run():
        handler, receiver = AsyncMock(), AsyncMock()
        handler.execute.return_value = ProcessingResult(
            ProcessingOutcome.TERMINAL_FINALIZED,
            DocumentFailure(
                "RETRY_EXHAUSTED", "Document processing attempts were exhausted."
            ),
        )
        await worker(handler).handle_delivery(receiver, delivery(), asyncio.Event())
        assert receiver.dead_letter_message.await_args.kwargs == {
            "reason": "RETRY_EXHAUSTED",
            "error_description": "Document processing attempts were exhausted.",
        }
        receiver.complete_message.assert_not_awaited()

    asyncio.run(run())


def test_lock_renewal_loss_cancels_and_settles_handler():
    async def run():
        entered, cleaned = asyncio.Event(), asyncio.Event()
        handler = AsyncMock()

        async def process(*args, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        handler.execute.side_effect = process
        value, receiver = worker(handler), AsyncMock()
        task = asyncio.create_task(
            value.handle_delivery(receiver, delivery(), asyncio.Event())
        )
        await entered.wait()
        callback = value._renewer.register.call_args.kwargs["on_lock_renew_failure"]
        await callback(None, MessageLockLostError(message="private"))
        await task
        assert cleaned.is_set()
        receiver.abandon_message.assert_awaited_once()
        receiver.dead_letter_message.assert_not_awaited()

    asyncio.run(run())


def test_dlq_browse_is_bounded_and_continues_sequence_between_passes():
    from azure.servicebus import ServiceBusSubQueue

    async def run():
        client, receiver, handler = MagicMock(), AsyncMock(), AsyncMock()
        client.get_queue_receiver.return_value = receiver
        handler.settle_exhausted.return_value = ProcessingResult(
            ProcessingOutcome.SUCCESS
        )
        messages = [delivery() for _ in range(5)]
        for number, message in enumerate(messages):
            message.sequence_number = number
            message.dead_letter_reason = "MaxDeliveryCountExceeded"

        async def peek(*, max_message_count, sequence_number):
            return messages[sequence_number : sequence_number + max_message_count]

        receiver.peek_messages.side_effect = peek
        value = AzureServiceBusDocumentWorker(
            client=client,
            queue_name="documents",
            handler=handler,
            auto_lock_renewer=MagicMock(),
            dlq_pass_limit=2,
        )
        assert await value.browse_dlq_once(asyncio.Event()) == 2
        assert await value.browse_dlq_once(asyncio.Event()) == 2
        assert await value.browse_dlq_once(asyncio.Event()) == 1
        assert handler.settle_exhausted.await_count == 5
        assert [
            c.kwargs["sequence_number"] for c in receiver.peek_messages.await_args_list
        ] == [0, 2, 4, 5]
        assert value._dlq_sequence == 0
        assert all(
            c.kwargs["sub_queue"] is ServiceBusSubQueue.DEAD_LETTER
            for c in client.get_queue_receiver.call_args_list
        )
        receiver.complete_message.assert_not_awaited()
        receiver.dead_letter_message.assert_not_awaited()
        handler.execute.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["invalid", "foreign", "application", "retry"])
def test_dlq_invalid_foreign_and_application_dlq_are_safe(mode):
    async def run():
        client, receiver, handler = MagicMock(), AsyncMock(), AsyncMock()
        client.get_queue_receiver.return_value = receiver
        message = delivery([b"invalid"] if mode == "invalid" else None)
        message.sequence_number = 0
        message.dead_letter_reason = (
            "MALFORMED_DOCUMENT"
            if mode == "application"
            else "MaxDeliveryCountExceeded"
        )
        receiver.peek_messages.side_effect = [[message], []]
        handler.settle_exhausted.return_value = ProcessingResult(
            ProcessingOutcome.RETRYABLE
            if mode == "retry"
            else ProcessingOutcome.SUCCESS
        )
        if mode == "foreign":
            handler.settle_exhausted.side_effect = ProcessingRequestRejected()
        value = worker(handler, client)
        assert await value.browse_dlq_once(asyncio.Event()) == 1
        assert handler.settle_exhausted.await_count == (
            1 if mode in ("foreign", "retry") else 0
        )
        assert value._dlq_sequence == 0
        handler.execute.assert_not_awaited()

    asyncio.run(run())


def test_dlq_browse_deadline_closes_receiver():
    async def run():
        client, receiver = MagicMock(), AsyncMock()
        client.get_queue_receiver.return_value = receiver

        async def peek(**kwargs):
            await asyncio.Event().wait()

        receiver.peek_messages.side_effect = peek
        value = AzureServiceBusDocumentWorker(
            client=client,
            queue_name="documents",
            handler=AsyncMock(),
            auto_lock_renewer=MagicMock(),
            dlq_pass_seconds=0.01,
        )
        with pytest.raises(TimeoutError):
            await value.browse_dlq_once(asyncio.Event())
        receiver.__aexit__.assert_awaited_once()

    asyncio.run(run())


def test_missing_delivery_metadata_is_not_assumed_first_attempt():
    async def run():
        handler, receiver, message = AsyncMock(), AsyncMock(), delivery()
        del message.delivery_count
        await worker(handler).handle_delivery(receiver, message, asyncio.Event())
        handler.execute.assert_not_awaited()
        receiver.abandon_message.assert_awaited_once()

    asyncio.run(run())


def test_dlq_retryable_record_does_not_starve_later_records():
    async def run():
        client, receiver, handler = MagicMock(), AsyncMock(), AsyncMock()
        client.get_queue_receiver.return_value = receiver
        messages = [delivery(), delivery()]
        for number, message in enumerate(messages):
            message.sequence_number = number
            message.dead_letter_reason = "MaxDeliveryCountExceeded"
        receiver.peek_messages.side_effect = [messages, []]
        handler.settle_exhausted.side_effect = [
            ProcessingResult(ProcessingOutcome.RETRYABLE),
            ProcessingResult(ProcessingOutcome.SUCCESS),
        ]
        value = worker(handler, client)
        assert await value.browse_dlq_once(asyncio.Event()) == 2
        assert handler.settle_exhausted.await_count == 2
        assert value._dlq_sequence == 0

    asyncio.run(run())
