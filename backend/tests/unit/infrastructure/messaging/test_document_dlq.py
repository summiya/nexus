import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from azure.servicebus import ServiceBusReceiveMode, ServiceBusSubQueue
from tests.unit.infrastructure.messaging.test_document_processing import delivery

from nexus.documents.ports.processing import (
    ProcessingOutcome,
    ProcessingRequestRejected,
    ProcessingResult,
)
from nexus.infrastructure.messaging.azure_service_bus_document_dlq import (
    AzureServiceBusDocumentDlqReconciler,
)


def context(**bounds):
    client, receiver, handler, requests = (
        MagicMock(),
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
    )
    client.get_queue_receiver.return_value = receiver
    requests.matches.return_value = True
    handler.settle_exhausted.return_value = ProcessingResult(ProcessingOutcome.SUCCESS)
    reconciler = AzureServiceBusDocumentDlqReconciler(
        client=client,
        queue_name="documents",
        handler=handler,
        requests=requests,
        **bounds,
    )
    return reconciler, client, receiver, handler, requests


def message(reason="MaxDeliveryCountExceeded"):
    result = delivery()
    result.dead_letter_reason = reason
    return result


def test_bounded_pass_consumes_and_removes_historical_records():
    async def run():
        value, client, receiver, handler, _ = context(pass_limit=2)
        pending = [message() for _ in range(5)]
        completed = []

        async def receive(**kwargs):
            return [pending.pop(0)] if pending else []

        async def complete(record):
            completed.append(record)

        receiver.receive_messages.side_effect = receive
        receiver.complete_message.side_effect = complete
        assert await value.reconcile_once(asyncio.Event()) == 2
        assert await value.reconcile_once(asyncio.Event()) == 2
        assert await value.reconcile_once(asyncio.Event()) == 1
        assert await value.reconcile_once(asyncio.Event()) == 0
        assert len(completed) == handler.settle_exhausted.await_count == 5
        kwargs = client.get_queue_receiver.call_args.kwargs
        assert kwargs == {
            "queue_name": "documents",
            "sub_queue": ServiceBusSubQueue.DEAD_LETTER,
            "receive_mode": ServiceBusReceiveMode.PEEK_LOCK,
            "prefetch_count": 0,
            "max_wait_time": 5,
        }
        receiver.peek_messages.assert_not_awaited()
        receiver.abandon_message.assert_not_awaited()
        receiver.dead_letter_message.assert_not_awaited()
        handler.execute.assert_not_awaited()
        client.close.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize(
    "mode", ["success", "ttl", "terminal", "retry", "invalid", "foreign", "rejected"]
)
def test_record_settlement(mode):
    async def run():
        value, _, receiver, handler, requests = context()
        record = message(
            "TTLExpiredException" if mode == "ttl" else "MaxDeliveryCountExceeded"
        )
        if mode == "terminal":
            record.dead_letter_reason = "MALFORMED_DOCUMENT"
        if mode == "invalid":
            record.body = [b"private-invalid"]
        if mode == "foreign":
            requests.matches.return_value = False
        if mode == "rejected":
            handler.settle_exhausted.side_effect = ProcessingRequestRejected()
        if mode == "retry":
            handler.settle_exhausted.return_value = ProcessingResult(
                ProcessingOutcome.RETRYABLE
            )
        receiver.receive_messages.side_effect = [[record], []]
        assert await value.reconcile_once(asyncio.Event()) == 1
        if mode == "retry":
            receiver.abandon_message.assert_awaited_once_with(record)
            receiver.complete_message.assert_not_awaited()
        else:
            receiver.complete_message.assert_awaited_once_with(record)
            receiver.abandon_message.assert_not_awaited()
        if mode in ("terminal", "invalid", "foreign"):
            handler.settle_exhausted.assert_not_awaited()
        handler.execute.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True])
def test_deadline_and_cancellation_abandon_and_close_receiver(cancel):
    async def run():
        value, _, receiver, handler, _ = context(pass_seconds=0.02)
        entered = asyncio.Event()

        async def block(request):
            entered.set()
            await asyncio.Event().wait()

        handler.settle_exhausted.side_effect = block
        record = message()
        receiver.receive_messages.return_value = [record]
        task = asyncio.create_task(value.reconcile_once(asyncio.Event()))
        await entered.wait()
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
            await task
        receiver.abandon_message.assert_awaited_once_with(record)
        receiver.__aexit__.assert_awaited_once()

    asyncio.run(run())


def test_retryable_record_does_not_prevent_later_record_settlement():
    async def run():
        value, _, receiver, handler, _ = context(pass_limit=2)
        records = [message(), message()]
        receiver.receive_messages.side_effect = [[records[0]], [records[1]]]
        handler.settle_exhausted.side_effect = [
            ProcessingResult(ProcessingOutcome.RETRYABLE),
            ProcessingResult(ProcessingOutcome.SUCCESS),
        ]
        assert await value.reconcile_once(asyncio.Event()) == 2
        receiver.abandon_message.assert_awaited_once_with(records[0])
        receiver.complete_message.assert_awaited_once_with(records[1])

    asyncio.run(run())


def test_reader_failure_is_abandoned_not_removed():
    async def run():
        value, _, receiver, _, requests = context()
        record = message("MALFORMED_DOCUMENT")
        receiver.receive_messages.return_value = [record]
        requests.matches.side_effect = RuntimeError("private provider")
        with pytest.raises(RuntimeError):
            await value.reconcile_once(asyncio.Event())
        receiver.complete_message.assert_not_awaited()
        receiver.abandon_message.assert_awaited_once_with(record)
        receiver.__aexit__.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize("fatal", [False, True])
def test_reconciler_retries_transient_transport_but_stops_on_fatal(fatal, monkeypatch):
    from azure.servicebus.exceptions import (
        ServiceBusAuthenticationError,
        ServiceBusError,
    )

    async def run():
        value, _, _, _, _ = context()
        stop = asyncio.Event()
        error = (ServiceBusAuthenticationError if fatal else ServiceBusError)(
            message="private"
        )
        value.reconcile_once = AsyncMock(side_effect=error)

        async def pause(*args, **kwargs):
            args[0].close()
            stop.set()

        monkeypatch.setattr(asyncio, "wait_for", pause)
        if fatal:
            with pytest.raises(ServiceBusAuthenticationError):
                await value.run(stop)
        else:
            await value.run(stop)
        value.reconcile_once.assert_awaited_once()

    asyncio.run(run())
