"""Provider-neutral structured extraction boundary and safe failures."""

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


class DocumentExtractionError(Exception):
    def __init__(self, reason: DocumentExtractionFailure) -> None:
        super().__init__("Document extraction failed")
        self.reason = reason


class DocumentExtractor(Protocol):
    """Consume verified EOF before returning; the caller owns the source context."""

    async def extract(self, source: DocumentSource) -> ExtractedDocument: ...
