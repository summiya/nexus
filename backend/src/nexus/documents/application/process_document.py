"""Durable request admission and the single delivery-level reliability policy."""

import asyncio
import hashlib
from datetime import UTC, datetime

from nexus.documents.application.processing_failures import (
    RETRY_EXHAUSTED,
    ProcessingVersionConflict,
    classify_processing_failure,
)
from nexus.documents.domain import Document, DocumentStatus
from nexus.documents.ports.chunk_persistence import DocumentChunkPersistence
from nexus.documents.ports.persistence import DocumentConflictError, DocumentPersistence
from nexus.documents.ports.processing import (
    DocumentFinalization,
    DocumentProcessingRequested,
    DocumentProcessor,
    DocumentRequestReader,
    ProcessingOutcome,
    ProcessingRequestRejected,
    ProcessingResult,
)
from nexus.logging import get_logger

logger = get_logger(__name__)


class ProcessDocument:
    def __init__(
        self,
        *,
        requests: DocumentRequestReader,
        documents: DocumentPersistence,
        processor: DocumentProcessor,
        chunks: DocumentChunkPersistence,
        finalizer: DocumentFinalization,
        processing_version: str,
        attempt_timeout_seconds: float = 240,
    ) -> None:
        if (
            not isinstance(processing_version, str)
            or not processing_version.strip()
            or processing_version != processing_version.strip()
            or len(processing_version) > 128
        ):
            raise ValueError("Invalid processing version")
        if (
            type(attempt_timeout_seconds) not in (int, float)
            or not 0 < attempt_timeout_seconds <= 540
        ):
            raise ValueError("Invalid processing deadline")
        self._requests = requests
        self._documents = documents
        self._processor = processor
        self._chunks = chunks
        self._finalizer = finalizer
        self._version = processing_version
        self._timeout = attempt_timeout_seconds

    async def execute(
        self,
        message: DocumentProcessingRequested,
        *,
        final_attempt: bool = False,
    ) -> ProcessingResult:
        document = None
        try:
            document = await self._admit(message)
            if document.status in (DocumentStatus.COMPLETED, DocumentStatus.FAILED):
                return ProcessingResult(ProcessingOutcome.SUCCESS)
            if document.processing_version != self._version:
                # A committed original-generation result needs no new recipe execution.
                if (
                    await self._chunks.get_chunk_set(
                        organization_public_id=document.organization_public_id,
                        document_public_id=document.public_id,
                    )
                    is not None
                ):
                    return await self._finalize(document)
                raise ProcessingVersionConflict()
            async with asyncio.timeout(self._timeout):
                await self._processor.process(document=document, request=message)
            return ProcessingResult(ProcessingOutcome.SUCCESS)
        except ProcessingRequestRejected:
            raise
        except Exception as exc:  # noqa: BLE001 - classify only safe provider-neutral policy
            if document is None:
                return ProcessingResult(ProcessingOutcome.RETRYABLE)
            return await self._failed(document, message, exc, final_attempt)

    async def _admit(self, message: DocumentProcessingRequested) -> Document:
        if not await self._requests.matches(message):
            raise ProcessingRequestRejected("Document processing request rejected")
        document = await self._documents.get_document(
            organization_public_id=message.organization_public_id,
            document_public_id=message.document_public_id,
        )
        if document is None:
            raise ProcessingRequestRejected("Document processing request rejected")
        if document.status is not DocumentStatus.QUEUED:
            return document
        started = document.start_processing(
            at=max(datetime.now(UTC), document.created_at),
            processing_version=self._version,
        )
        try:
            await self._documents.update_document(expected=document, document=started)
            return started
        except DocumentConflictError:
            current = await self._documents.get_document(
                organization_public_id=message.organization_public_id,
                document_public_id=message.document_public_id,
            )
            if current is not None and current.status is not DocumentStatus.QUEUED:
                return current
            raise

    async def _failed(
        self,
        document: Document,
        message: DocumentProcessingRequested,
        error: Exception,
        final_attempt: bool,
    ) -> ProcessingResult:
        classified = classify_processing_failure(error)
        logger.warning(
            "document_processing_attempt_failed",
            error_type=type(error).__name__,
            failure_code=classified.failure.code,
            correlation=hashlib.sha256(
                str(message.request_public_id).encode()
            ).hexdigest()[:16],
        )
        try:
            # Stale CAS and concurrent terminal outcomes must reconcile before exhaustion.
            current = await self._documents.get_document(
                organization_public_id=document.organization_public_id,
                document_public_id=document.public_id,
            )
            if current is not None and current.status in (
                DocumentStatus.COMPLETED,
                DocumentStatus.FAILED,
            ):
                return ProcessingResult(ProcessingOutcome.SUCCESS)
            if classified.retryable and not final_attempt:
                return ProcessingResult(ProcessingOutcome.RETRYABLE)
            failure = (
                RETRY_EXHAUSTED.failure if classified.retryable else classified.failure
            )
            return await self._finalizer.finalize(
                organization_public_id=document.organization_public_id,
                document_public_id=document.public_id,
                failure=failure,
            )
        except Exception as exc:  # noqa: BLE001 - no DLQ before lifecycle durability
            logger.warning("document_finalization_retry", error_type=type(exc).__name__)
            return ProcessingResult(ProcessingOutcome.RETRYABLE)

    async def _finalize(self, document: Document) -> ProcessingResult:
        return await self._finalizer.finalize(
            organization_public_id=document.organization_public_id,
            document_public_id=document.public_id,
        )

    async def settle_exhausted(
        self, message: DocumentProcessingRequested
    ) -> ProcessingResult:
        """DLQ reconciliation never executes the processing pipeline."""
        try:
            document = await self._admit(message)
            if document.status in (DocumentStatus.COMPLETED, DocumentStatus.FAILED):
                return ProcessingResult(ProcessingOutcome.SUCCESS)
            return await self._finalizer.finalize(
                organization_public_id=document.organization_public_id,
                document_public_id=document.public_id,
                failure=RETRY_EXHAUSTED.failure,
            )
        except ProcessingRequestRejected:
            raise
        except Exception as exc:  # noqa: BLE001 - retry browsing after infrastructure recovery
            logger.warning("document_exhaustion_retry", error_type=type(exc).__name__)
            return ProcessingResult(ProcessingOutcome.RETRYABLE)
