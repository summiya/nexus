"""Bounded Document DLQ reconciliation; never replay the processing pipeline."""

import asyncio

from azure.servicebus import (
    ServiceBusReceivedMessage,
    ServiceBusReceiveMode,
    ServiceBusSubQueue,
)
from azure.servicebus.aio import ServiceBusClient, ServiceBusReceiver
from azure.servicebus.exceptions import (
    MessagingEntityDisabledError,
    MessagingEntityNotFoundError,
    ServiceBusAuthenticationError,
    ServiceBusAuthorizationError,
    ServiceBusError,
)

from nexus.documents.ports.processing import (
    DocumentMessageHandler,
    DocumentRequestReader,
    ProcessingOutcome,
    ProcessingRequestRejected,
)
from nexus.infrastructure.messaging._document_processing_message import (
    decode_document_message,
)
from nexus.logging import get_logger

logger = get_logger(__name__)
_FATAL_ERRORS = (
    ServiceBusAuthenticationError,
    ServiceBusAuthorizationError,
    MessagingEntityNotFoundError,
    MessagingEntityDisabledError,
)


class AzureServiceBusDocumentDlqReconciler:
    def __init__(
        self,
        *,
        client: ServiceBusClient,
        queue_name: str,
        handler: DocumentMessageHandler,
        requests: DocumentRequestReader,
        pass_limit: int = 100,
        pass_seconds: float = 10,
    ) -> None:
        if (
            type(pass_limit) is not int
            or not 1 <= pass_limit <= 1000
            or type(pass_seconds) not in (int, float)
            or not 0 < pass_seconds <= 60
        ):
            raise ValueError("Invalid document DLQ bounds")
        self._client = client
        self._queue = queue_name
        self._handler = handler
        self._requests = requests
        self._limit = pass_limit
        self._seconds = pass_seconds

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.reconcile_once(stop)
            except _FATAL_ERRORS:
                raise
            except Exception as exc:  # noqa: BLE001 - retry after bounded infrastructure failure
                logger.warning("document_dlq_retry", error_type=type(exc).__name__)
            try:
                await asyncio.wait_for(stop.wait(), timeout=10)
            except TimeoutError:
                pass

    async def reconcile_once(self, stop: asyncio.Event) -> int:
        inspected = 0
        receiver = self._client.get_queue_receiver(
            queue_name=self._queue,
            sub_queue=ServiceBusSubQueue.DEAD_LETTER,
            receive_mode=ServiceBusReceiveMode.PEEK_LOCK,
            prefetch_count=0,
            max_wait_time=5,
        )
        # Hold retryable records until the pass ends, allowing later records through.
        unsettled: list[ServiceBusReceivedMessage] = []
        async with receiver:
            try:
                async with asyncio.timeout(self._seconds):
                    while inspected < self._limit and not stop.is_set():
                        messages = await receiver.receive_messages(
                            max_message_count=min(20, self._limit - inspected),
                            max_wait_time=5,
                        )
                        if not messages:
                            break
                        unsettled.extend(messages)
                        for message in messages:
                            if stop.is_set():
                                break
                            inspected += 1
                            if await self._reconcile(receiver, message):
                                unsettled.remove(message)
            finally:
                for message in unsettled:
                    try:
                        await receiver.abandon_message(message)
                    except ServiceBusError as exc:
                        logger.warning(
                            "document_dlq_settlement_retry",
                            error_type=type(exc).__name__,
                        )
        return inspected

    async def _reconcile(
        self, receiver: ServiceBusReceiver, message: ServiceBusReceivedMessage
    ) -> bool:
        try:
            request = decode_document_message(message)
        except (ValueError, TypeError):
            logger.warning("document_dlq_request_invalid")
            await receiver.complete_message(message)
            return True
        # Reader failures are infrastructure failures, not evidence of an invalid record.
        if not await self._requests.matches(request):
            logger.warning("document_dlq_request_invalid")
            await receiver.complete_message(message)
            return True
        if message.dead_letter_reason in (
            "MaxDeliveryCountExceeded",
            "TTLExpiredException",
        ):
            try:
                result = await self._handler.settle_exhausted(request)
            except ProcessingRequestRejected:
                logger.warning("document_dlq_request_invalid")
            else:
                if result.outcome is ProcessingOutcome.RETRYABLE:
                    return False
        # Application-terminal records already have durable lifecycle settlement.
        await receiver.complete_message(message)
        return True
