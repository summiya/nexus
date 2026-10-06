"""Conservative, linear canonicalization of already extracted content."""

import re
import unicodedata
from enum import StrEnum

from nexus.documents.domain.extracted_document import (
    ExtractedBlockKind,
    ExtractedDocument,
)
from nexus.documents.domain.normalized_document import (
    NormalizedBlock,
    NormalizedDocument,
)

NORMALIZER_ID = "nexus.normalization"
NORMALIZER_VERSION = "1"
DEFAULT_MAX_NORMALIZATION_BLOCKS = 50_000
DEFAULT_MAX_NORMALIZATION_BYTES = 8 * 1024 * 1024


class DocumentNormalizationFailure(StrEnum):
    EMPTY = "empty"
    RESOURCE_LIMIT = "resource_limit"
    ARTIFACT_MISMATCH = "artifact_mismatch"


class DocumentNormalizationError(Exception):
    def __init__(self, reason: DocumentNormalizationFailure) -> None:
        super().__init__("Document normalization failed")
        self.reason = reason


def text_size_bytes(text: str, *, maximum: int) -> int:
    # Stop at the bound without allocating one large UTF-8 copy.
    size = 0
    for start in range(0, len(text), 8192):
        size += len(text[start : start + 8192].encode("utf-8"))
        if size > maximum:
            raise DocumentNormalizationError(
                DocumentNormalizationFailure.RESOURCE_LIMIT
            )
    return size


def _canonical_text(text: str, kind: ExtractedBlockKind) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if kind in (ExtractedBlockKind.CODE, ExtractedBlockKind.RAW):
        return text
    text = unicodedata.normalize("NFC", text)
    lines = [line.rstrip(" \t") for line in text.split("\n")]
    if kind in (ExtractedBlockKind.PARAGRAPH, ExtractedBlockKind.HEADING):
        start, end = 0, len(lines)
        while start < end and not lines[start].strip():
            start += 1
        while end > start and not lines[end - 1].strip():
            end -= 1
        lines = lines[start:end]
    text = "\n".join(lines)
    if kind is ExtractedBlockKind.HEADING:
        text = re.sub(r"[ \t]+", " ", text).strip(" ")
    return text


class NormalizeDocument:
    def __init__(
        self,
        *,
        max_blocks: int = DEFAULT_MAX_NORMALIZATION_BLOCKS,
        max_input_bytes: int = DEFAULT_MAX_NORMALIZATION_BYTES,
        max_text_bytes: int = DEFAULT_MAX_NORMALIZATION_BYTES,
    ) -> None:
        if any(
            type(value) is not int or value < 1
            for value in (max_blocks, max_input_bytes, max_text_bytes)
        ):
            raise ValueError("Invalid normalization limits")
        self._max_blocks = max_blocks
        self._max_input_bytes = max_input_bytes
        self._max_text_bytes = max_text_bytes

    def execute(self, document: ExtractedDocument) -> NormalizedDocument:
        if len(document.blocks) > self._max_blocks:
            raise DocumentNormalizationError(
                DocumentNormalizationFailure.RESOURCE_LIMIT
            )
        blocks: list[NormalizedBlock] = []
        headings: list[tuple[int, int]] = []
        input_bytes = 0
        text_bytes = 0
        meaningful = False
        for block in document.blocks:
            input_bytes += text_size_bytes(
                block.text, maximum=self._max_input_bytes - input_bytes
            )
            text = _canonical_text(block.text, block.kind)
            text_bytes += text_size_bytes(
                text, maximum=self._max_text_bytes - text_bytes
            )
            meaningful = meaningful or bool(text.strip())
            if block.kind is ExtractedBlockKind.HEADING and text.strip():
                # Extraction has already validated the heading level.
                level = block.heading_level
                assert level is not None
                while headings and headings[-1][0] >= level:
                    headings.pop()
                headings.append((level, block.index))
            blocks.append(
                NormalizedBlock(
                    block.index,
                    block.kind,
                    text,
                    block.start_line,
                    block.end_line,
                    block.heading_level,
                    block.list_item,
                    block.quote_depth,
                    block.page_number,
                    tuple(index for _, index in headings),
                )
            )
        if not meaningful:
            raise DocumentNormalizationError(DocumentNormalizationFailure.EMPTY)
        return NormalizedDocument(
            document.source_file_public_id,
            document.source_entity_tag,
            document.extractor_id,
            document.extractor_version,
            NORMALIZER_ID,
            NORMALIZER_VERSION,
            tuple(blocks),
            document.page_count,
        )
