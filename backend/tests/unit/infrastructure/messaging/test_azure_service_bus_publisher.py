import asyncio
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from azure.servicebus.exceptions import (
    MessagingEntityDisabledError,
    MessagingEntityNotFoundError,
    ServiceBusAuthenticationError,
    ServiceBusAuthorizationError,
    ServiceBusError,
)

from nexus.infrastructure.messaging.azure_service_bus_publisher import (
    AzureServiceBusPublicationError,
    AzureServiceBusQueuePublisher,
)


def client_and_sender():
    client, sender = MagicMock(), AsyncMock()
    client.close = AsyncMock()
    sender.__aenter__.return_value = sender
    client.get_queue_sender.return_value = sender
    return client, sender


@pytest.mark.parametrize("content_type", [None, "application/octet-stream"])
def test_exact_message_and_sender_lifecycle_without_closing_client(content_type):
    async def run():
        client, sender = client_and_sender()
        kwargs = {} if content_type is None else {"content_type": content_type}
        await AzureServiceBusQueuePublisher(client).publish(
            queue_name="custom-queue",
            body=b"\x00exact-body",
            message_id="stable-id",
            **kwargs,
        )
        client.get_queue_sender.assert_called_once_with(queue_name="custom-queue")
        sender.__aenter__.assert_awaited_once_with()
        sender.send_messages.assert_awaited_once()
        message = sender.send_messages.await_args.args[0]
        assert b"".join(message.body) == b"\x00exact-body"
        assert message.message_id == "stable-id"
        assert message.content_type == (content_type or "application/json")
        sender.__aexit__.assert_awaited_once_with(None, None, None)
        client.close.assert_not_called()

    asyncio.run(run())


def test_each_publication_gets_a_separate_sender():
    async def run():
        client, first = client_and_sender()
        second = AsyncMock()
        second.__aenter__.return_value = second
        client.get_queue_sender.side_effect = [first, second]
        publisher = AzureServiceBusQueuePublisher(client)
        for queue in ("first", "second"):
            await publisher.publish(
                queue_name=queue, body=queue.encode(), message_id=queue
            )
        assert client.get_queue_sender.call_args_list == [
            call(queue_name="first"),
            call(queue_name="second"),
        ]
        for sender, queue in ((first, "first"), (second, "second")):
            sender.__aenter__.assert_awaited_once()
            sender.__aexit__.assert_awaited_once()
            sender.send_messages.assert_awaited_once()
            assert sender.send_messages.await_args.args[0].message_id == queue
        client.close.assert_not_called()

    asyncio.run(run())


def test_concurrent_publications_have_independent_sender_state():
    async def run():
        client = MagicMock()
        client.close = AsyncMock()
        senders = [AsyncMock(), AsyncMock()]
        started = [asyncio.Event(), asyncio.Event()]
        release = asyncio.Event()
        for index, sender in enumerate(senders):
            sender.__aenter__.return_value = sender

            async def send(message, index=index):
                started[index].set()
                await release.wait()
                assert message.message_id == str(index)
                assert b"".join(message.body) == str(index).encode()

            sender.send_messages.side_effect = send
        client.get_queue_sender.side_effect = senders
        publisher = AzureServiceBusQueuePublisher(client)
        tasks = [
            asyncio.create_task(
                publisher.publish(
                    queue_name=f"queue-{i}", body=str(i).encode(), message_id=str(i)
                )
            )
            for i in range(2)
        ]
        try:
            await asyncio.wait_for(
                asyncio.gather(*(event.wait() for event in started)), timeout=2
            )
            assert all(not task.done() for task in tasks)
            assert client.get_queue_sender.call_args_list == [
                call(queue_name="queue-0"),
                call(queue_name="queue-1"),
            ]
        finally:
            release.set()
            await asyncio.gather(*tasks)
        for sender in senders:
            sender.__aenter__.assert_awaited_once()
            sender.send_messages.assert_awaited_once()
            sender.__aexit__.assert_awaited_once_with(None, None, None)
        client.close.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize(
    "error_type",
    [
        ServiceBusAuthenticationError,
        ServiceBusAuthorizationError,
        MessagingEntityNotFoundError,
        MessagingEntityDisabledError,
    ],
)
@pytest.mark.parametrize("stage", ["creation", "enter", "send", "exit"])
def test_fatal_errors_are_safe_and_chained_without_closing_client(error_type, stage):
    async def run():
        client, sender = client_and_sender()
        original = error_type(message="private-provider-details")
        if stage == "creation":
            client.get_queue_sender.side_effect = original
        elif stage == "enter":
            sender.__aenter__.side_effect = original
        elif stage == "send":
            sender.send_messages.side_effect = original
        else:
            sender.__aexit__.side_effect = original
        with pytest.raises(AzureServiceBusPublicationError) as exc:
            await AzureServiceBusQueuePublisher(client).publish(
                queue_name="queue", body=b"private-body", message_id="id"
            )
        assert str(exc.value) == "Azure Service Bus publication configuration failed"
        assert exc.value.__cause__ is original
        assert "private" not in str(exc.value)
        if stage in {"send", "exit"}:
            sender.__aexit__.assert_awaited_once()
        client.close.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize(
    "original",
    [
        ServiceBusError(message="transient"),
        RuntimeError("ordinary"),
        TimeoutError("timeout"),
    ],
)
def test_other_errors_propagate_unchanged_and_cleanup_sender(original):
    async def run():
        client, sender = client_and_sender()
        sender.send_messages.side_effect = original
        with pytest.raises(type(original)) as exc:
            await AzureServiceBusQueuePublisher(client).publish(
                queue_name="queue", body=b"body", message_id="id"
            )
        assert exc.value is original
        sender.__aexit__.assert_awaited_once()
        # Propagation adds caller frames after the context has exited.
        error_type, error, traceback = sender.__aexit__.await_args.args
        assert error_type is type(original) and error is original
        assert traceback is not None
        client.close.assert_not_called()

    asyncio.run(run())


def test_cancellation_propagates_and_exits_sender_without_closing_client():
    async def run():
        client, sender = client_and_sender()
        entered = asyncio.Event()
        original = asyncio.CancelledError()

        async def send(message):
            entered.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                raise original

        sender.send_messages.side_effect = send
        task = asyncio.create_task(
            AzureServiceBusQueuePublisher(client).publish(
                queue_name="queue", body=b"body", message_id="id"
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError) as exc:
            await task
        assert exc.value is original
        sender.__aexit__.assert_awaited_once()
        assert sender.__aexit__.await_args.args[:2] == (
            asyncio.CancelledError,
            original,
        )
        client.close.assert_not_called()

    asyncio.run(run())


def test_publication_error_has_a_fixed_message_only():
    assert (
        str(AzureServiceBusPublicationError())
        == "Azure Service Bus publication configuration failed"
    )
    with pytest.raises(TypeError):
        AzureServiceBusPublicationError("private")
