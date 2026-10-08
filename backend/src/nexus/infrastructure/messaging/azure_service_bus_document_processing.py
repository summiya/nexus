"""Azure transport for the versioned, bounded Document processing message."""

import asyncio
import hashlib
from typing import Any

from azure.servicebus import (
    ServiceBusReceivedMessage,
    ServiceBusReceiveMode,
)
from azure.servicebus.aio import AutoLockRenewer, ServiceBusClient, ServiceBusReceiver
from azure.servicebus.exceptions import (
    MessageAlreadySettled,
    MessageLockLostError,
    MessagingEntityDisabledError,
    MessagingEntityNotFoundError,
    ServiceBusAuthenticationError,
    ServiceBusAuthorizationError,
    ServiceBusError,
)

from nexus.documents.ports.dispatch import DocumentPublicationError
from nexus.documents.ports.processing import (
    DocumentMessageHandler,
    DocumentProcessingRequested,
    DocumentRequestReader,
    ProcessingOutcome,
    ProcessingRequestRejected,
    ProcessingResult,
)
from nexus.infrastructure.messaging._document_processing_message import (
    MAX_DOCUMENT_MESSAGE_BYTES,
    decode_document_message,
    encode_document_message,
)
from nexus.infrastructure.messaging.azure_service_bus_document_dlq import (
    AzureServiceBusDocumentDlqReconciler,
)
from nexus.infrastructure.messaging.azure_service_bus_publisher import (
    AzureServiceBusPublicationError,
    AzureServiceBusQueuePublisher,
)
from nexus.logging import get_logger

__all__ = [
    "MAX_DOCUMENT_MESSAGE_BYTES",
    "AzureServiceBusDocumentPublisher",
    "AzureServiceBusDocumentWorker",
    "decode_document_message",
    "encode_document_message",
]

logger = get_logger(__name__)
_FATAL_ERRORS = (
    ServiceBusAuthenticationError,
    ServiceBusAuthorizationError,
    MessagingEntityNotFoundError,
    MessagingEntityDisabledError,
)


class AzureServiceBusDocumentPublisher:
    def __init__(
        self, publisher: AzureServiceBusQueuePublisher, queue_name: str
    ) -> None:
        self._publisher = publisher
        self._queue = queue_name

    async def publish(self, message: DocumentProcessingRequested) -> None:
        try:
            await self._publisher.publish(
                queue_name=self._queue,
                body=encode_document_message(message),
                message_id=str(message.request_public_id),
                content_type="application/json",
            )
        except AzureServiceBusPublicationError as exc:
            raise DocumentPublicationError(
                "Document publication configuration failed"
            ) from exc


class AzureServiceBusDocumentWorker:
    def __init__(
        self,
        *,
        client: ServiceBusClient,
        queue_name: str,
        handler: DocumentMessageHandler,
        requests: DocumentRequestReader,
        auto_lock_renewer: AutoLockRenewer,
        concurrency: int = 2,
        max_delivery_count: int = 10,
        dlq_pass_limit: int = 100,
        dlq_pass_seconds: float = 10,
    ) -> None:
        if not 1 <= concurrency <= 20:
            raise ValueError("Invalid document worker concurrency")
        if type(max_delivery_count) is not int or not 1 <= max_delivery_count <= 100:
            raise ValueError("Invalid document delivery count")
        self._max_deliveries = max_delivery_count
        self._dlq = AzureServiceBusDocumentDlqReconciler(
            client=client,
            queue_name=queue_name,
            handler=handler,
            requests=requests,
            pass_limit=dlq_pass_limit,
            pass_seconds=dlq_pass_seconds,
        )
        self._client = client
        self._queue = queue_name
        self._handler = handler
        self._renewer = auto_lock_renewer
        self._concurrency = concurrency

    async def run(self, stop: asyncio.Event) -> None:
        async with asyncio.TaskGroup() as workers:
            for _ in range(self._concurrency):
                workers.create_task(self._receive_slot(stop))
            workers.create_task(self._dlq.run(stop))

    async def _receive_slot(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                receiver = self._client.get_queue_receiver(
                    queue_name=self._queue,
                    receive_mode=ServiceBusReceiveMode.PEEK_LOCK,
                    prefetch_count=0,
                    max_wait_time=5,
                )
                async with receiver:
                    while not stop.is_set():
                        messages = await receiver.receive_messages(
                            max_message_count=1, max_wait_time=5
                        )
                        for message in messages:
                            failed = await self.handle_delivery(receiver, message, stop)
                            if failed:
                                await _wait_for_stop(stop, 2)
            except _FATAL_ERRORS:
                raise
            except ServiceBusError as exc:
                logger.warning(
                    "document_receiver_reconnecting", error_type=type(exc).__name__
                )
                await _wait_for_stop(stop, 2)

    async def handle_delivery(
        self,
        receiver: ServiceBusReceiver,
        message: ServiceBusReceivedMessage,
        stop: asyncio.Event,
    ) -> bool:
        correlation = hashlib.sha256(str(message.message_id).encode()).hexdigest()[:16]
        try:
            request = decode_document_message(message)
        except (ValueError, TypeError):
            await self._settle(receiver, message, "reject")
            return False
        if stop.is_set():
            await self._settle(receiver, message, "abandon")
            return False
        count = getattr(message, "delivery_count", None)
        if type(count) is not int or count < 0:
            logger.warning(
                "document_delivery_metadata_invalid", correlation=correlation
            )
            await self._settle(receiver, message, "abandon")
            return True
        attempt = count + 1
        renewal_failed = asyncio.Event()

        async def renewal_failure(renewable: Any, error: Exception | None) -> None:
            del renewable, error
            renewal_failed.set()

        self._renewer.register(receiver, message, on_lock_renew_failure=renewal_failure)
        handler = asyncio.create_task(
            self._handler.execute(
                request, final_attempt=attempt >= self._max_deliveries
            )
        )
        stopped = asyncio.create_task(stop.wait())
        lost_lock = asyncio.create_task(renewal_failed.wait())
        try:
            await asyncio.wait(
                (handler, stopped, lost_lock), return_when=asyncio.FIRST_COMPLETED
            )
            if stop.is_set() or renewal_failed.is_set():
                await _cancel_handler(handler)
                await self._settle(receiver, message, "abandon")
                return False
            try:
                result = await handler
            except ProcessingRequestRejected:
                await self._settle(receiver, message, "reject")
                return False
            except Exception as exc:  # noqa: BLE001 - safe transport retry
                logger.warning(
                    "document_handler_failed",
                    error_type=type(exc).__name__,
                    correlation=correlation,
                )
                await self._settle(receiver, message, "abandon")
                return True
            logger.info(
                "document_processing_outcome",
                outcome=result.outcome.value,
                attempt=attempt,
                correlation=correlation,
            )
            if result.outcome is ProcessingOutcome.RETRYABLE:
                await self._settle(receiver, message, "abandon")
                return True
            if result.outcome is ProcessingOutcome.TERMINAL_FINALIZED:
                await self._settle(receiver, message, "terminal", result)
            else:
                await self._settle(receiver, message, "complete")
            return False
        except asyncio.CancelledError:
            await _cancel_handler(handler)
            await self._settle(receiver, message, "abandon")
            raise
        finally:
            stopped.cancel()
            lost_lock.cancel()
            await asyncio.gather(stopped, lost_lock, return_exceptions=True)

    async def _settle(
        self,
        receiver: ServiceBusReceiver,
        message: ServiceBusReceivedMessage,
        action: str,
        result: ProcessingResult | None = None,
    ) -> None:
        try:
            if action == "reject":
                await receiver.dead_letter_message(
                    message,
                    reason="INVALID_DOCUMENT_PROCESSING_REQUEST",
                    error_description="The document processing request is invalid.",
                )
            elif (
                action == "terminal"
                and result is not None
                and result.failure is not None
            ):
                await receiver.dead_letter_message(
                    message,
                    reason=result.failure.code,
                    error_description=result.failure.safe_message,
                )
            elif action == "complete":
                await receiver.complete_message(message)
            else:
                await receiver.abandon_message(message)
        except (ServiceBusError, MessageAlreadySettled, MessageLockLostError) as exc:
            logger.warning("document_settlement_failed", error_type=type(exc).__name__)


async def _cancel_handler(task: asyncio.Task[ProcessingResult]) -> None:
    task.cancel()
    # Persistence may shield its commit: settle that boundary before abandonment.
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except Exception:  # noqa: BLE001 - cancellation remains authoritative
            break
    if not task.cancelled():
        task.exception()


async def _wait_for_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass
