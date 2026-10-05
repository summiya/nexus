"""Azure outbound queue publication using a borrowed application-owned client."""

from azure.servicebus import ServiceBusMessage
from azure.servicebus.aio import ServiceBusClient
from azure.servicebus.exceptions import (
    MessagingEntityDisabledError,
    MessagingEntityNotFoundError,
    ServiceBusAuthenticationError,
    ServiceBusAuthorizationError,
)

_FATAL_PUBLICATION_ERRORS = (
    ServiceBusAuthenticationError,
    ServiceBusAuthorizationError,
    MessagingEntityNotFoundError,
    MessagingEntityDisabledError,
)


class AzureServiceBusPublicationError(Exception):
    def __init__(self) -> None:
        super().__init__("Azure Service Bus publication configuration failed")


class AzureServiceBusQueuePublisher:
    def __init__(self, client: ServiceBusClient) -> None:
        self._client = client

    async def publish(
        self,
        *,
        queue_name: str,
        body: bytes,
        message_id: str,
        content_type: str = "application/json",
    ) -> None:
        # Each publication owns its sender; the shared client belongs to composition.
        try:
            async with self._client.get_queue_sender(queue_name=queue_name) as sender:
                await sender.send_messages(
                    ServiceBusMessage(
                        body, message_id=message_id, content_type=content_type
                    )
                )
        except _FATAL_PUBLICATION_ERRORS as exc:
            raise AzureServiceBusPublicationError() from exc
