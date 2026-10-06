"""Provider-neutral synchronous segmentation and fixed-message failures."""

from enum import StrEnum
from typing import Protocol

from nexus.documents.domain.normalized_document import NormalizedDocument
from nexus.documents.domain.segmented_document import SegmentedDocument


class DocumentSegmentationFailure(StrEnum):
    EMPTY = "empty"
    RESOURCE_LIMIT = "resource_limit"


class DocumentSegmentationError(Exception):
    def __init__(self, reason: DocumentSegmentationFailure) -> None:
        super().__init__("Document segmentation failed")
        self.reason = reason


class DocumentSegmenter(Protocol):
    def execute(self, document: NormalizedDocument) -> SegmentedDocument: ...
