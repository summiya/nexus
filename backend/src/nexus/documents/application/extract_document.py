"""Extract a verified source; no lifecycle mutations or persistence."""

from nexus.documents.application.formats import document_format
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
        pdf: DocumentExtractor,
    ) -> None:
        self._source = source
        self._txt = txt
        self._markdown = markdown
        self._pdf = pdf

    async def execute(
        self, *, document: Document, request: DocumentProcessingRequested
    ) -> ExtractedDocument:
        async with self._source.open(document=document, request=request) as source:
            source_format = document_format(source.original_name, source.mime_type)
            if source_format == ".txt":
                return await self._txt.extract(source)
            if source_format == ".md":
                return await self._markdown.extract(source)
            if source_format == ".pdf":
                return await self._pdf.extract(source)
            raise DocumentExtractionError(DocumentExtractionFailure.UNSUPPORTED)
