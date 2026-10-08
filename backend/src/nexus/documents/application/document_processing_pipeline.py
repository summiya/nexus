"""Successful processing only; delivery policy belongs to DocumentProcessingHandler."""

import asyncio
import hashlib
from collections.abc import Callable
from time import monotonic

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
from nexus.logging import get_logger

logger = get_logger(__name__)


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
        correlation = hashlib.sha256(
            str(request.request_public_id).encode()
        ).hexdigest()[:16]
        existing = await self._chunks.get_chunk_set(
            organization_public_id=document.organization_public_id,
            document_public_id=document.public_id,
        )
        if existing is not None:
            await self._complete(document)
            logger.info(
                "document_processing_committed_output_resumed",
                request_correlation=correlation,
            )
            return
        if document.processing_version != self._version:
            raise ProcessingVersionConflict()
        started = monotonic()
        extracted = await self._extraction.execute(document=document, request=request)
        _stage_completed(
            "extraction",
            started,
            correlation,
            block_count=len(extracted.blocks),
            page_count=extracted.page_count,
            extractor_id=extracted.extractor_id,
            extractor_version=extracted.extractor_version,
        )
        document = await self._record_extractor(document, extracted.extractor_version)
        if document.status is not DocumentStatus.PROCESSING:
            return
        started = monotonic()
        normalized = await _transform(lambda: self._normalization.execute(extracted))
        _stage_completed(
            "normalization",
            started,
            correlation,
            block_count=len(normalized.blocks),
            normalizer_id=normalized.normalizer_id,
            normalizer_version=normalized.normalizer_version,
        )
        started = monotonic()
        await self._artifacts.execute(
            normalized, organization_public_id=document.organization_public_id
        )
        _stage_completed("artifact", started, correlation)
        started = monotonic()
        segmented = await _transform(lambda: self._segmentation.execute(normalized))
        _stage_completed(
            "segmentation",
            started,
            correlation,
            chunk_count=len(segmented.chunks),
            segmenter_id=segmented.segmenter_id,
            segmenter_version=segmented.segmenter_version,
        )
        started = monotonic()
        await self._chunks.persist_chunk_set(
            expected=document, segmented_document=segmented
        )
        _stage_completed(
            "chunks", started, correlation, chunk_count=len(segmented.chunks)
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


def _stage_completed(
    stage: str, started: float, correlation: str, **counts: object
) -> None:
    logger.info(
        "document_processing_stage_completed",
        stage=stage,
        duration_ms=round((monotonic() - started) * 1000, 3),
        request_correlation=correlation,
        **counts,
    )
