"""Native PDF extraction with deterministic, page-selective managed OCR."""

from nexus.documents.domain.extracted_document import (
    ExtractedBlock,
    ExtractedBlockKind,
    ExtractedDocument,
)
from nexus.documents.ports.extraction import (
    DocumentExtractionError,
    DocumentExtractionFailure,
    OcrBlock,
    PdfPageOcr,
)
from nexus.documents.ports.source import DocumentSource
from nexus.infrastructure.extraction.pdf import (
    PDF_EXTRACTOR_ID,
    PDF_EXTRACTOR_VERSION,
    PdfDocumentExtractor,
)

PDF_OCR_EXTRACTOR_ID = "nexus.pdf-ocr"
PDF_OCR_EXTRACTOR_VERSION = "1"


class PdfWithOcrDocumentExtractor:
    def __init__(self, native: PdfDocumentExtractor, ocr: PdfPageOcr) -> None:
        self._native = native
        self._ocr = ocr

    async def extract(self, source: DocumentSource) -> ExtractedDocument:
        data, pages = await self._native.inspect_source(source)
        selected = tuple(page.page_number for page in pages if page.needs_ocr)
        replacements: dict[int, tuple[OcrBlock, ...]] = {}
        if selected:
            ocr_pages = await self._ocr.extract_pages(data, page_numbers=selected)
            if tuple(page.page_number for page in ocr_pages) != selected:
                raise DocumentExtractionError(
                    DocumentExtractionFailure.PROVIDER_FAILURE
                )
            replacements = {page.page_number: page.blocks for page in ocr_pages}

        blocks: list[ExtractedBlock] = []
        text_bytes = 0
        for page in pages:
            page_blocks = replacements.get(page.page_number)
            if page_blocks is None:
                page_blocks = tuple(
                    OcrBlock(ExtractedBlockKind.PARAGRAPH, text) for text in page.texts
                )
            for block in page_blocks:
                text = block.text
                if not text.strip():
                    continue
                text_bytes += len(text.encode("utf-8"))
                if (
                    len(blocks) >= self._native.max_blocks
                    or text_bytes > self._native.max_text_bytes
                ):
                    raise DocumentExtractionError(
                        DocumentExtractionFailure.RESOURCE_LIMIT
                    )
                blocks.append(
                    ExtractedBlock(
                        len(blocks),
                        block.kind,
                        text,
                        page_number=page.page_number,
                    )
                )
        if not blocks:
            raise DocumentExtractionError(DocumentExtractionFailure.EMPTY)
        return ExtractedDocument(
            source.source_file_public_id,
            source.entity_tag,
            PDF_OCR_EXTRACTOR_ID if selected else PDF_EXTRACTOR_ID,
            PDF_OCR_EXTRACTOR_VERSION if selected else PDF_EXTRACTOR_VERSION,
            tuple(blocks),
            len(pages),
        )
