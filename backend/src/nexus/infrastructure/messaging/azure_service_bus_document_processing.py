"""Azure transport for the versioned, bounded Document processing message."""

import asyncio
import hashlib
import json
from dataclasses import asdict
from typing import Any, cast
from uuid import UUID

from azure.servicebus import (
    ServiceBusMessage,
    ServiceBusReceivedMessage,
    ServiceBusReceiveMode,
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
    ProcessingRequestRejected,
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
    def __init__(self, client: ServiceBusClient, queue_name: str) -> None:
        self._client = client
        self._queue = queue_name

    async def publish(self, message: DocumentProcessingRequested) -> None:
        # Each bounded send owns its sender; no shared-link concurrency assumptions.
        try:
            async with self._client.get_queue_sender(queue_name=self._queue) as sender:
                await sender.send_messages(
                    ServiceBusMessage(
                        encode_document_message(message),
                        message_id=str(message.request_public_id),
                        content_type="application/json",
                    )
                )
        except _FATAL_ERRORS as exc:
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
    ) -> None:
        if not 1 <= concurrency <= 20:
            raise ValueError("Invalid document worker concurrency")
        self._client = client
        self._queue = queue_name
        self._handler = handler
        self._renewer = auto_lock_renewer
        self._concurrency = concurrency

    async def run(self, stop: asyncio.Event) -> None:
        async with asyncio.TaskGroup() as workers:
            for _ in range(self._concurrency):
                workers.create_task(self._receive_slot(stop))

    async def _receive_slot(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                receiver = self._client.get_queue_receiver(
                    queue_name=self._queue,
                    receive_mode=ServiceBusReceiveMode.PEEK_LOCK,
                    prefetch_count=0,
                    max_wait_time=5,
                    auto_lock_renewer=cast(Any, self._renewer),
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
        handler = asyncio.create_task(self._handler.execute(request))
        stopped = asyncio.create_task(stop.wait())
        try:
            await asyncio.wait((handler, stopped), return_when=asyncio.FIRST_COMPLETED)
            if stop.is_set():
                await _cancel_handler(handler)
                await self._settle(receiver, message, "abandon")
                return False
            try:
                await handler
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
            await self._settle(receiver, message, "complete")
            return False
        except asyncio.CancelledError:
            await _cancel_handler(handler)
            await self._settle(receiver, message, "abandon")
            raise
        finally:
            stopped.cancel()
            await asyncio.gather(stopped, return_exceptions=True)

    async def _settle(
        self,
        receiver: ServiceBusReceiver,
        message: ServiceBusReceivedMessage,
        action: str,
    ) -> None:
        try:
            if action == "reject":
                await receiver.dead_letter_message(
                    message,
                    reason="INVALID_DOCUMENT_PROCESSING_REQUEST",
                    error_description="The document processing request is invalid.",
                )
            elif action == "complete":
                await receiver.complete_message(message)
            else:
                await receiver.abandon_message(message)
        except (ServiceBusError, MessageAlreadySettled, MessageLockLostError) as exc:
            logger.warning("document_settlement_failed", error_type=type(exc).__name__)


async def _cancel_handler(task: asyncio.Task[None]) -> None:
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
