"""Provider-neutral processing message and processor boundary."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from nexus.documents.domain import Document


@dataclass(frozen=True)
class DocumentProcessingRequested:
    request_public_id: UUID
    organization_public_id: UUID
    document_public_id: UUID
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("Unsupported document processing message")
        if any(
            not isinstance(v, UUID) or v.int == 0
            for v in (
                self.request_public_id,
                self.organization_public_id,
                self.document_public_id,
            )
        ):
            raise ValueError("Invalid document processing identity")


class ProcessingRequestRejected(Exception):
    """The delivery does not identify a durable request in its tenant."""


class DocumentRequestReader(Protocol):
    async def matches(self, message: DocumentProcessingRequested) -> bool: ...


class DocumentProcessor(Protocol):
    """A real downstream implementation owns processing after the claim."""

    async def process(
        self, *, document: Document, request: DocumentProcessingRequested
    ) -> None: ...


class DocumentMessageHandler(Protocol):
    async def execute(self, message: DocumentProcessingRequested) -> None: ...
