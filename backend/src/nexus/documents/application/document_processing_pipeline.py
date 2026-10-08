"""Successful processing only; delivery policy belongs to DocumentProcessingHandler."""

import asyncio
from collections.abc import Callable

from nexus.documents.application.extract_document import ExtractDocument
from nexus.documents.application.normalize_document import NormalizeDocument
from nexus.documents.application.processing_failures import ProcessingVersionConflict
from nexus.documents.application.write_normalized_artifact import (
    WriteNormalizedArtifact,
)
from nexus.documents.domain import Document, DocumentStatus
from nexus.documents.ports.chunk_persistence import DocumentChunkPersistence
from nexus.documents.ports.persistence import DocumentConflictError, DocumentPersistence
from nexus.documents.ports.processing import (
    DocumentFinalization,
    DocumentProcessingRequested,
)
from nexus.documents.ports.segmentation import DocumentSegmenter


class DocumentProcessingPipeline:
    def __init__(
        self,
        *,
        documents: DocumentPersistence,
        chunks: DocumentChunkPersistence,
        finalizer: DocumentFinalization,
        extraction: ExtractDocument,
        normalization: NormalizeDocument,
        artifacts: WriteNormalizedArtifact,
        segmentation: DocumentSegmenter,
        processing_version: str,
    ) -> None:
        self._documents = documents
        self._chunks = chunks
        self._finalizer = finalizer
        self._extraction = extraction
        self._normalization = normalization
        self._artifacts = artifacts
        self._segmentation = segmentation
        self._version = processing_version

    async def process(
        self, *, document: Document, request: DocumentProcessingRequested
    ) -> None:
        existing = await self._chunks.get_chunk_set(
            organization_public_id=document.organization_public_id,
            document_public_id=document.public_id,
        )
        if existing is not None:
            await self._complete(document)
            return
        if document.processing_version != self._version:
            raise ProcessingVersionConflict()
        extracted = await self._extraction.execute(document=document, request=request)
        document = await self._record_extractor(document, extracted.extractor_version)
        if document.status is not DocumentStatus.PROCESSING:
            return
        normalized = await _transform(lambda: self._normalization.execute(extracted))
        await self._artifacts.execute(
            normalized, organization_public_id=document.organization_public_id
        )
        segmented = await _transform(lambda: self._segmentation.execute(normalized))
        await self._chunks.persist_chunk_set(
            expected=document, segmented_document=segmented
        )
        await self._complete(document)

    async def _record_extractor(self, document: Document, version: str) -> Document:
        if document.extractor_version is not None:
            if document.extractor_version != version:
                raise ProcessingVersionConflict()
            return document
        recorded = document.record_extractor_version(version)
        try:
            await self._documents.update_document(expected=document, document=recorded)
            return recorded
        except DocumentConflictError:
            current = await self._documents.get_document(
                organization_public_id=document.organization_public_id,
                document_public_id=document.public_id,
            )
            if current is None:
                raise
            if current.status in (DocumentStatus.COMPLETED, DocumentStatus.FAILED):
                return current
            if current.processing_version != self._version:
                raise ProcessingVersionConflict() from None
            if current.extractor_version == version:
                return current
            if current.extractor_version is not None:
                raise ProcessingVersionConflict() from None
            raise

    async def _complete(self, document: Document) -> None:
        await self._finalizer.finalize(
            organization_public_id=document.organization_public_id,
            document_public_id=document.public_id,
        )


async def _transform[T](operation: Callable[[], T]) -> T:
    """Keep the caller's bounded worker slot until its pure transformation settles."""
    task = asyncio.create_task(asyncio.to_thread(operation))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:  # noqa: BLE001 - cancellation remains authoritative
                break
        if not task.cancelled():
            task.exception()
        raise
