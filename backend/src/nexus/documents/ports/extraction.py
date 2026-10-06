"""Provider-neutral structured extraction boundary and safe failures."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from nexus.documents.domain.extracted_document import ExtractedDocument
from nexus.documents.ports.source import DocumentSource


class DocumentExtractionFailure(StrEnum):
    UNSUPPORTED = "unsupported"
    EMPTY = "empty"
    MALFORMED = "malformed"
    RESOURCE_LIMIT = "resource_limit"
    PARSER_FAILURE = "parser_failure"
    ENCRYPTED = "encrypted"
    PROVIDER_ACCESS = "provider_access"
    PROVIDER_TRANSIENT = "provider_transient"
    PROVIDER_FAILURE = "provider_failure"


class DocumentExtractionError(Exception):
    def __init__(self, reason: DocumentExtractionFailure) -> None:
        super().__init__("Document extraction failed")
        self.reason = reason


class DocumentExtractor(Protocol):
    """Consume verified EOF before returning; the caller owns the source context."""

    async def extract(self, source: DocumentSource) -> ExtractedDocument: ...


@dataclass(frozen=True, repr=False)
class OcrPage:
    """Original PDF page and ordered logical text blocks; empty pages are valid."""

    page_number: int
    texts: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.page_number) is not int or self.page_number < 1:
            raise ValueError("Invalid OCR page number")
        if type(self.texts) is not tuple or any(
            type(text) is not str for text in self.texts
        ):
            raise ValueError("Invalid OCR text blocks")


class PdfPageOcr(Protocol):
    async def extract_pages(
        self, pdf_bytes: bytes, *, page_numbers: tuple[int, ...]
    ) -> tuple[OcrPage, ...]:
        """Analyze bounded verified PDF bytes, preserving requested original pages."""
        ...
