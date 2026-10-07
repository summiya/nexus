"""Provider-neutral processing message and processor boundary."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from nexus.documents.domain import Document, DocumentFailure
from nexus.documents.ports.source import DocumentSourceFacts


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

    async def get_source_facts(
        self, message: DocumentProcessingRequested
    ) -> DocumentSourceFacts | None: ...


class DocumentProcessor(Protocol):
    """A real downstream implementation owns processing after the claim."""

    async def process(
        self, *, document: Document, request: DocumentProcessingRequested
    ) -> None: ...


class ProcessingOutcome(StrEnum):
    SUCCESS = "success"
    RETRYABLE = "retryable"
    TERMINAL_FINALIZED = "terminal_finalized"


@dataclass(frozen=True)
class ProcessingResult:
    outcome: ProcessingOutcome
    failure: DocumentFailure | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, ProcessingOutcome):
            raise TypeError("Invalid processing outcome")
        if self.failure is not None and not isinstance(self.failure, DocumentFailure):
            raise ValueError("Invalid processing failure")
        if (self.outcome is ProcessingOutcome.TERMINAL_FINALIZED) != (
            self.failure is not None
        ):
            raise ValueError("Invalid processing outcome metadata")


class DocumentFinalization(Protocol):
    async def finalize(
        self,
        *,
        organization_public_id: UUID,
        document_public_id: UUID,
        failure: DocumentFailure | None = None,
    ) -> ProcessingResult: ...


class DocumentMessageHandler(Protocol):
    async def execute(
        self,
        message: DocumentProcessingRequested,
        *,
        final_attempt: bool = False,
    ) -> ProcessingResult: ...

    async def settle_exhausted(
        self, message: DocumentProcessingRequested
    ) -> ProcessingResult: ...
