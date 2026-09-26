"""Azure Service Bus transport for committed File upload events."""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, cast

from azure.servicebus import ServiceBusReceivedMessage, ServiceBusReceiveMode
from azure.servicebus.aio import AutoLockRenewer, ServiceBusClient, ServiceBusReceiver
from azure.servicebus.amqp import AmqpMessageBodyType
from azure.servicebus.exceptions import (
    MessageLockLostError,
    ServiceBusAuthenticationError,
    ServiceBusError,
)

from nexus.files.ports import UploadCompletionEvent, UploadCompletionHandler
from nexus.infrastructure.storage import (
    AzureBlobCreatedEventMapper,
    AzureBlobCreatedEventMappingError,
)
from nexus.logging import get_logger

MAX_UPLOAD_COMPLETION_MESSAGE_BODY_BYTES = 65_536

_INVALID_BODY_REASON = "INVALID_MESSAGE_BODY"
_INVALID_EVENT_REASON = "INVALID_BLOB_CREATED_EVENT"
_INVALID_BODY_DESCRIPTION = "The message body is not a valid upload event."
_INVALID_EVENT_DESCRIPTION = "The BlobCreated event is invalid."
_RECEIVE_WAIT_SECONDS = 5.0
_RECONNECT_DELAY_SECONDS = 2.0
_INITIAL_FAILURE_DELAY_SECONDS = 2.0
_MAX_FAILURE_DELAY_SECONDS = 60.0
_SAFE_CORRELATION_LENGTH = 16

logger = get_logger(__name__)


class InvalidUploadCompletionMessageBody(ValueError):
    """A Service Bus body cannot be decoded as one CloudEvent object."""


class _ProcessingOutcome(Enum):
    HANDLED = "handled"
    HANDLED_SETTLEMENT_FAILED = "handled_settlement_failed"
    HANDLER_FAILED = "handler_failed"
    PERMANENTLY_REJECTED = "permanently_rejected"
    STOPPED = "stopped"
    SETTLEMENT_FAILED = "settlement_failed"


def decode_upload_completion_body(
    message: ServiceBusReceivedMessage,
) -> Mapping[str, object]:
    """Decode one bounded AMQP DATA body into a JSON object."""

    if message.body_type is not AmqpMessageBodyType.DATA:
        raise InvalidUploadCompletionMessageBody(_INVALID_BODY_DESCRIPTION)

    body = message.body
    try:
        iterator = iter((body,) if isinstance(body, bytes) else body)
    except TypeError:
        raise InvalidUploadCompletionMessageBody(_INVALID_BODY_DESCRIPTION) from None

    decoded = bytearray()
    for section in iterator:
        if not isinstance(section, bytes):
            raise InvalidUploadCompletionMessageBody(_INVALID_BODY_DESCRIPTION)
        if len(decoded) + len(section) > MAX_UPLOAD_COMPLETION_MESSAGE_BODY_BYTES:
            raise InvalidUploadCompletionMessageBody(_INVALID_BODY_DESCRIPTION)
        decoded.extend(section)

    if not decoded:
        raise InvalidUploadCompletionMessageBody(_INVALID_BODY_DESCRIPTION)

    try:
        payload = json.loads(bytes(decoded).decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise InvalidUploadCompletionMessageBody(_INVALID_BODY_DESCRIPTION) from None
    if not isinstance(payload, dict):
        raise InvalidUploadCompletionMessageBody(_INVALID_BODY_DESCRIPTION)
    if not all(isinstance(key, str) for key in payload):
        raise InvalidUploadCompletionMessageBody(_INVALID_BODY_DESCRIPTION)
    return cast(dict[str, object], payload)


@dataclass(frozen=True)
class AzureServiceBusUploadCompletionWorker:
    """Receive, map, dispatch, and settle one File event at a time."""

    client: ServiceBusClient
    queue_name: str
    mapper: AzureBlobCreatedEventMapper
    handler: UploadCompletionHandler
    auto_lock_renewer: AutoLockRenewer
    jitter: Callable[[float, float], float] = field(
        default=random.uniform,
        repr=False,
    )

    async def run(self, stop_event: asyncio.Event) -> None:
        """Run until shutdown while recreating recoverable receiver links."""

        consecutive_handler_failures = 0
        logger.info("file_upload_completion_worker_started")
        try:
            while not stop_event.is_set():
                try:
                    receiver = self.client.get_queue_receiver(
                        queue_name=self.queue_name,
                        receive_mode=ServiceBusReceiveMode.PEEK_LOCK,
                        prefetch_count=0,
                        max_wait_time=_RECEIVE_WAIT_SECONDS,
                        # azure-servicebus 7.14.3 annotates this async-client
                        # argument with the synchronous renewer type even though
                        # the aio renewer is the supported runtime value.
                        auto_lock_renewer=cast(Any, self.auto_lock_renewer),
                    )
                    async with receiver:
                        while not stop_event.is_set():
                            messages = await receiver.receive_messages(
                                max_message_count=1,
                                max_wait_time=_RECEIVE_WAIT_SECONDS,
                            )
                            if not messages:
                                continue
                            outcome = await self._process_message(
                                receiver,
                                messages[0],
                                stop_event,
                            )
                            if outcome is _ProcessingOutcome.STOPPED:
                                return
                            if outcome is _ProcessingOutcome.HANDLER_FAILED:
                                consecutive_handler_failures += 1
                                delay = self._failure_delay(
                                    consecutive_handler_failures
                                )
                                logger.warning(
                                    "file_upload_completion_receive_delayed",
                                    delay_seconds=delay,
                                )
                                if await _wait_for_stop(stop_event, delay):
                                    return
                            elif outcome in {
                                _ProcessingOutcome.HANDLED,
                                _ProcessingOutcome.HANDLED_SETTLEMENT_FAILED,
                            }:
                                consecutive_handler_failures = 0
                except asyncio.CancelledError:
                    raise
                except ServiceBusAuthenticationError:
                    logger.error("file_upload_completion_authentication_failed")
                    raise
                except ServiceBusError as exc:
                    logger.warning(
                        "file_upload_completion_receiver_disconnected",
                        error_type=type(exc).__name__,
                    )
                    if await _wait_for_stop(stop_event, _RECONNECT_DELAY_SECONDS):
                        return
                    logger.info("file_upload_completion_receiver_reconnecting")
        finally:
            logger.info("file_upload_completion_worker_stopped")

    async def _process_message(
        self,
        receiver: ServiceBusReceiver,
        message: ServiceBusReceivedMessage,
        stop_event: asyncio.Event,
    ) -> _ProcessingOutcome:
        message_correlation = _safe_message_correlation(message)
        try:
            payload = decode_upload_completion_body(message)
        except InvalidUploadCompletionMessageBody:
            return await self._dead_letter(
                receiver,
                message,
                reason=_INVALID_BODY_REASON,
                description=_INVALID_BODY_DESCRIPTION,
                correlation=message_correlation,
            )

        try:
            event = self.mapper.map_event(payload)
        except AzureBlobCreatedEventMappingError:
            return await self._dead_letter(
                receiver,
                message,
                reason=_INVALID_EVENT_REASON,
                description=_INVALID_EVENT_DESCRIPTION,
                correlation=message_correlation,
            )

        event_correlation = _safe_event_correlation(event)
        if stop_event.is_set():
            await self._abandon_for_shutdown(receiver, message, event_correlation)
            return _ProcessingOutcome.STOPPED

        handler_task = asyncio.create_task(self.handler.handle(event))
        stop_task = asyncio.create_task(stop_event.wait())
        try:
            done, _pending = await asyncio.wait(
                {handler_task, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop_task in done and handler_task not in done:
                handler_task.cancel()
                await _settle_cancelled_task(handler_task)
                await self._abandon_for_shutdown(
                    receiver,
                    message,
                    event_correlation,
                )
                return _ProcessingOutcome.STOPPED

            stop_task.cancel()
            await _settle_cancelled_task(stop_task)
            await handler_task
        except asyncio.CancelledError:
            handler_task.cancel()
            stop_task.cancel()
            await _settle_cancelled_task(handler_task)
            await _settle_cancelled_task(stop_task)
            await self._abandon_for_shutdown(receiver, message, event_correlation)
            raise
        except Exception as exc:  # noqa: BLE001 - unexpected handlers are retryable
            stop_task.cancel()
            await _settle_cancelled_task(stop_task)
            logger.warning(
                "file_upload_completion_handler_failed",
                correlation=event_correlation,
                error_type=type(exc).__name__,
            )
            await self._abandon_after_failure(
                receiver,
                message,
                event_correlation,
            )
            return _ProcessingOutcome.HANDLER_FAILED

        try:
            await receiver.complete_message(message)
        except (ServiceBusError, MessageLockLostError) as exc:
            logger.warning(
                "file_upload_completion_complete_failed",
                correlation=event_correlation,
                error_type=type(exc).__name__,
            )
            return _ProcessingOutcome.HANDLED_SETTLEMENT_FAILED

        logger.info(
            "file_upload_completion_handled",
            correlation=event_correlation,
        )
        return _ProcessingOutcome.HANDLED

    async def _dead_letter(
        self,
        receiver: ServiceBusReceiver,
        message: ServiceBusReceivedMessage,
        *,
        reason: str,
        description: str,
        correlation: str,
    ) -> _ProcessingOutcome:
        try:
            await receiver.dead_letter_message(
                message,
                reason=reason,
                error_description=description,
            )
        except (ServiceBusError, MessageLockLostError) as exc:
            logger.warning(
                "file_upload_completion_dead_letter_failed",
                correlation=correlation,
                reason=reason,
                error_type=type(exc).__name__,
            )
            return _ProcessingOutcome.SETTLEMENT_FAILED

        logger.warning(
            "file_upload_completion_dead_lettered",
            correlation=correlation,
            reason=reason,
        )
        return _ProcessingOutcome.PERMANENTLY_REJECTED

    async def _abandon_after_failure(
        self,
        receiver: ServiceBusReceiver,
        message: ServiceBusReceivedMessage,
        correlation: str,
    ) -> None:
        try:
            await receiver.abandon_message(message)
        except (ServiceBusError, MessageLockLostError) as exc:
            logger.warning(
                "file_upload_completion_abandon_failed",
                correlation=correlation,
                error_type=type(exc).__name__,
            )
            return
        logger.warning(
            "file_upload_completion_abandoned",
            correlation=correlation,
        )

    async def _abandon_for_shutdown(
        self,
        receiver: ServiceBusReceiver,
        message: ServiceBusReceivedMessage,
        correlation: str,
    ) -> None:
        try:
            await asyncio.shield(receiver.abandon_message(message))
        except (ServiceBusError, MessageLockLostError) as exc:
            logger.warning(
                "file_upload_completion_shutdown_abandon_failed",
                correlation=correlation,
                error_type=type(exc).__name__,
            )
            return
        logger.info(
            "file_upload_completion_shutdown_abandoned",
            correlation=correlation,
        )

    def _failure_delay(self, failure_count: int) -> float:
        exponent = min(max(failure_count - 1, 0), 5)
        nominal = min(
            _INITIAL_FAILURE_DELAY_SECONDS * (2**exponent),
            _MAX_FAILURE_DELAY_SECONDS,
        )
        minimum = nominal / 2
        return min(max(self.jitter(minimum, nominal), minimum), nominal)


async def _wait_for_stop(stop_event: asyncio.Event, delay: float) -> bool:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=delay)
    except TimeoutError:
        return False
    return True


async def _settle_cancelled_task[T](task: asyncio.Task[T]) -> None:
    try:
        await task
    except asyncio.CancelledError:
        return


def _safe_message_correlation(message: ServiceBusReceivedMessage) -> str:
    value = str(message.message_id or "missing")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[
        :_SAFE_CORRELATION_LENGTH
    ]


def _safe_event_correlation(event: UploadCompletionEvent) -> str:
    value = f"{event.source}\0{event.event_id}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[
        :_SAFE_CORRELATION_LENGTH
    ]


__all__ = [
    "MAX_UPLOAD_COMPLETION_MESSAGE_BODY_BYTES",
    "AzureServiceBusUploadCompletionWorker",
    "InvalidUploadCompletionMessageBody",
    "decode_upload_completion_body",
]
