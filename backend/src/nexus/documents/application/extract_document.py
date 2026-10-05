"""Extract a verified source; no lifecycle mutations or persistence."""

from pathlib import PurePosixPath

from nexus.documents.application.open_source import OpenDocumentSource
from nexus.documents.domain import Document
from nexus.documents.domain.extracted_document import ExtractedDocument
from nexus.documents.ports.extraction import (
    DocumentExtractionError,
    DocumentExtractionFailure,
    DocumentExtractor,
)
from nexus.documents.ports.processing import DocumentProcessingRequested


class ExtractDocument:
    def __init__(
        self,
        *,
        source: OpenDocumentSource,
        txt: DocumentExtractor,
        markdown: DocumentExtractor,
    ) -> None:
        self._source = source
        self._txt = txt
        self._markdown = markdown

    async def execute(
        self, *, document: Document, request: DocumentProcessingRequested
    ) -> ExtractedDocument:
        async with self._source.open(document=document, request=request) as source:
            suffix = PurePosixPath(source.original_name).suffix.lower()
            mime = source.mime_type.lower()
            if suffix == ".txt" and mime in {"text/plain", "application/octet-stream"}:
                return await self._txt.extract(source)
            if suffix == ".md" and mime in {
                "text/markdown",
                "text/plain",
                "application/octet-stream",
            }:
                return await self._markdown.extract(source)
            raise DocumentExtractionError(DocumentExtractionFailure.UNSUPPORTED)
