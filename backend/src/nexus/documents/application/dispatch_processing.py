"""Bounded outbox publication without a transaction around network I/O."""

import asyncio
import hashlib

from nexus.documents.ports.dispatch import (
    DispatchLease,
    DocumentDispatchPersistence,
    DocumentPublicationError,
    DocumentRequestPublisher,
)
from nexus.logging import get_logger

logger = get_logger(__name__)


class DispatchDocumentProcessing:
    def __init__(
        self,
        *,
        persistence: DocumentDispatchPersistence,
        publisher: DocumentRequestPublisher,
        concurrency: int = 2,
        lease_seconds: int = 60,
        send_timeout_seconds: int = 20,
        poll_seconds: float = 2,
    ) -> None:
        if (
            not 1 <= concurrency <= 20
            or not 0 < send_timeout_seconds < lease_seconds
            or poll_seconds <= 0
        ):
            raise ValueError("Invalid document dispatch bounds")
        self._persistence = persistence
        self._publisher = publisher
        self._concurrency = concurrency
        self._lease_seconds = lease_seconds
        self._timeout = send_timeout_seconds
        self._poll_seconds = poll_seconds

    async def dispatch_once(self) -> int:
        leases = await self._persistence.claim(
            limit=self._concurrency, lease_seconds=self._lease_seconds
        )
        async with asyncio.TaskGroup() as group:
            for lease in leases:
                group.create_task(self._send(lease))
        return len(leases)

    async def _send(self, lease: DispatchLease) -> None:
        try:
            async with asyncio.timeout(self._timeout):
                await self._publisher.publish(lease.message)
        except DocumentPublicationError:
            raise
        except Exception as exc:  # noqa: BLE001 - transport retry, no payload logging
            logger.warning("document_dispatch_failed", error_type=type(exc).__name__)
            await self._persistence.retry(
                lease, delay_seconds=min(60, 2 ** min(lease.attempt, 6))
            )
            return
        await self._persistence.acknowledge(lease)
        logger.info(
            "document_dispatch_acknowledged",
            request_correlation=hashlib.sha256(
                str(lease.message.request_public_id).encode()
            ).hexdigest()[:16],
        )

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.dispatch_once()
            except* DocumentPublicationError:
                raise
            except* Exception as exc:  # noqa: BLE001 - survive persistence outages
                logger.warning(
                    "document_dispatch_poll_failed", error_type=type(exc).__name__
                )
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._poll_seconds)
            except TimeoutError:
                pass
