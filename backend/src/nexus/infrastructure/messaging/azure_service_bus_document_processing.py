"""Azure transport for the versioned, bounded Document processing message."""

import asyncio
import hashlib
import json
from dataclasses import asdict
from typing import Any
from uuid import UUID

from azure.servicebus import (
    ServiceBusReceivedMessage,
    ServiceBusReceiveMode,
    ServiceBusSubQueue,
)
from azure.servicebus.aio import AutoLockRenewer, ServiceBusClient, ServiceBusReceiver
from azure.servicebus.amqp import AmqpMessageBodyType
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
    ProcessingOutcome,
    ProcessingRequestRejected,
    ProcessingResult,
)
from nexus.infrastructure.messaging.azure_service_bus_publisher import (
    AzureServiceBusPublicationError,
    AzureServiceBusQueuePublisher,
)
from nexus.logging import get_logger

MAX_DOCUMENT_MESSAGE_BYTES = 65_536
logger = get_logger(__name__)
_FATAL_ERRORS = (
    ServiceBusAuthenticationError,
    ServiceBusAuthorizationError,
    MessagingEntityNotFoundError,
    MessagingEntityDisabledError,
)


def encode_document_message(message: DocumentProcessingRequested) -> bytes:
    return json.dumps(
        asdict(message), default=str, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate message field")
        result[key] = value
    return result


def decode_document_message(
    message: ServiceBusReceivedMessage,
) -> DocumentProcessingRequested:
    if message.body_type is not AmqpMessageBodyType.DATA:
        raise ValueError("Invalid document message")
    body = message.body
    data = bytearray()
    for section in (body,) if isinstance(body, bytes) else body:
        if (
            not isinstance(section, bytes)
            or len(data) + len(section) > MAX_DOCUMENT_MESSAGE_BYTES
        ):
            raise ValueError("Invalid document message")
        data.extend(section)
    try:
        payload = json.loads(
            data.decode("utf-8", errors="strict"), object_pairs_hook=_unique_object
        )
        if not isinstance(payload, dict) or set(payload) != {
            "schema_version",
            "request_public_id",
            "organization_public_id",
            "document_public_id",
        }:
            raise ValueError("Invalid document message")
        if not all(
            isinstance(payload[key], str)
            for key in (
                "request_public_id",
                "organization_public_id",
                "document_public_id",
            )
        ):
            raise ValueError("Invalid document identity")
        return DocumentProcessingRequested(
            request_public_id=UUID(payload["request_public_id"]),
            organization_public_id=UUID(payload["organization_public_id"]),
            document_public_id=UUID(payload["document_public_id"]),
            schema_version=payload["schema_version"],
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, RecursionError) as exc:
        raise ValueError("Invalid document message") from exc


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
        if (
            type(dlq_pass_limit) is not int
            or not 1 <= dlq_pass_limit <= 1000
            or type(dlq_pass_seconds) not in (int, float)
            or not 0 < dlq_pass_seconds <= 60
        ):
            raise ValueError("Invalid document DLQ bounds")
        self._max_deliveries = max_delivery_count
        self._dlq_limit = dlq_pass_limit
        self._dlq_seconds = dlq_pass_seconds
        self._dlq_sequence = 0
        self._client = client
        self._queue = queue_name
        self._handler = handler
        self._renewer = auto_lock_renewer
        self._concurrency = concurrency

    async def run(self, stop: asyncio.Event) -> None:
        async with asyncio.TaskGroup() as workers:
            for _ in range(self._concurrency):
                workers.create_task(self._receive_slot(stop))
            workers.create_task(self._reconcile_dlq(stop))

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

    async def _reconcile_dlq(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.browse_dlq_once(stop)
            except _FATAL_ERRORS:
                raise
            except Exception as exc:  # noqa: BLE001 - safe bounded recovery pass
                logger.warning(
                    "document_dlq_browse_retry", error_type=type(exc).__name__
                )
            await _wait_for_stop(stop, 10)

    async def browse_dlq_once(self, stop: asyncio.Event) -> int:
        """Bounded non-destructive browse; no replay, checkpoint, or administration."""
        inspected = 0
        sequence = self._dlq_sequence
        receiver = self._client.get_queue_receiver(
            queue_name=self._queue,
            sub_queue=ServiceBusSubQueue.DEAD_LETTER,
            prefetch_count=0,
            max_wait_time=5,
        )
        async with asyncio.timeout(self._dlq_seconds), receiver:
            while inspected < self._dlq_limit and not stop.is_set():
                messages = await receiver.peek_messages(
                    max_message_count=min(20, self._dlq_limit - inspected),
                    sequence_number=sequence,
                )
                if not messages:
                    self._dlq_sequence = 0
                    break
                for message in messages:
                    if stop.is_set():
                        break
                    inspected += 1
                    number = message.sequence_number
                    if type(number) is not int or number < sequence:
                        raise ValueError("Invalid DLQ sequence")
                    sequence = number + 1
                    if message.dead_letter_reason not in (
                        "MaxDeliveryCountExceeded",
                        "TTLExpiredException",
                    ):
                        self._dlq_sequence = sequence
                        continue
                    try:
                        request = decode_document_message(message)
                        # Retained messages are revisited on the next cursor cycle,
                        # including retries; one unresolved record must not block others.
                        await self._handler.settle_exhausted(request)
                    except (ValueError, TypeError, ProcessingRequestRejected):
                        logger.warning("document_dlq_request_invalid")
                    self._dlq_sequence = sequence
        return inspected

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
