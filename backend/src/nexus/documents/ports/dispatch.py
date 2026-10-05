"""Durable dispatch leasing and publication contracts."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from nexus.documents.ports.processing import DocumentProcessingRequested


class DocumentDispatchError(Exception):
    """A durable dispatch operation failed; a later poll can retry."""


class DocumentPublicationError(Exception):
    """Fatal transport configuration failure; stop dispatch until corrected."""


@dataclass(frozen=True)
class DispatchLease:
    message: DocumentProcessingRequested
    token: UUID
    attempt: int


class DocumentDispatchPersistence(Protocol):
    async def claim(self, *, limit: int, lease_seconds: int) -> list[DispatchLease]: ...
    async def acknowledge(self, lease: DispatchLease) -> None: ...
    async def retry(self, lease: DispatchLease, *, delay_seconds: int) -> None: ...


class DocumentRequestPublisher(Protocol):
    async def publish(self, message: DocumentProcessingRequested) -> None: ...
