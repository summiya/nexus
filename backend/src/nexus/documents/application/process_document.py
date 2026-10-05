"""Validate a durable request and start its Document once."""

from datetime import UTC, datetime

from nexus.documents.domain import DocumentStatus
from nexus.documents.ports.persistence import DocumentConflictError, DocumentPersistence
from nexus.documents.ports.processing import (
    DocumentProcessingRequested,
    DocumentProcessor,
    DocumentRequestReader,
    ProcessingRequestRejected,
)


class ProcessDocument:
    def __init__(
        self,
        *,
        requests: DocumentRequestReader,
        documents: DocumentPersistence,
        processor: DocumentProcessor,
        processing_version: str,
    ) -> None:
        if (
            not processing_version.strip()
            or processing_version != processing_version.strip()
            or len(processing_version) > 128
        ):
            raise ValueError("Invalid processing version")
        self._requests = requests
        self._documents = documents
        self._processor = processor
        self._version = processing_version

    async def execute(self, message: DocumentProcessingRequested) -> None:
        if not await self._requests.matches(message):
            raise ProcessingRequestRejected("Document processing request rejected")
        document = await self._documents.get_document(
            organization_public_id=message.organization_public_id,
            document_public_id=message.document_public_id,
        )
        if document is None:
            raise ProcessingRequestRejected("Document processing request rejected")
        if document.status != DocumentStatus.QUEUED:
            return
        started = document.start_processing(
            at=datetime.now(UTC), processing_version=self._version
        )
        try:
            await self._documents.update_document(expected=document, document=started)
        except DocumentConflictError:
            current = await self._documents.get_document(
                organization_public_id=message.organization_public_id,
                document_public_id=message.document_public_id,
            )
            if current is not None and current.status != DocumentStatus.QUEUED:
                return
            raise
        # No transaction or connection is retained while processing.
        await self._processor.process(document=started, request=message)
