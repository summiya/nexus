"""Immutable in-memory chunks; source contributions remain authoritative."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from nexus.documents.domain.extracted_document import (
    ExtractedBlock,
    ExtractedBlockKind,
    ExtractedListItem,
)


class DocumentChunkKind(StrEnum):
    TEXT = "text"
    PARAGRAPH = "paragraph"
    LIST = "list"
    CODE = "code"
    RAW = "raw"
    HEADING = "heading"


@dataclass(frozen=True, repr=False)
class SourceContribution:
    source_block_index: int
    kind: ExtractedBlockKind
    start_line: int | None = None
    end_line: int | None = None
    page_number: int | None = None
    list_item: ExtractedListItem | None = None
    quote_depth: int = 0
    text_start: int | None = None
    text_end: int | None = None

    def __post_init__(self) -> None:
        # Reuse the source contract without inventing precise lines for slices.
        ExtractedBlock(
            self.source_block_index,
            self.kind,
            "",
            self.start_line,
            self.end_line,
            1 if self.kind is ExtractedBlockKind.HEADING else None,
            self.list_item,
            self.quote_depth,
            self.page_number,
        )
        if self.list_item is not None and not isinstance(
            self.list_item, ExtractedListItem
        ):
            raise ValueError("Invalid list contribution")
        if (self.text_start is not None or self.text_end is not None) and (
            type(self.text_start) is not int
            or type(self.text_end) is not int
            or not 0 <= self.text_start < self.text_end
        ):
            raise ValueError("Invalid normalized text slice")


@dataclass(frozen=True, repr=False)
class DocumentChunkCandidate:
    index: int
    kind: DocumentChunkKind
    text: str
    section_path: tuple[int, ...]
    contributions: tuple[SourceContribution, ...]

    def __post_init__(self) -> None:
        if type(self.index) is not int or self.index < 0:
            raise ValueError("Invalid chunk order")
        if (
            not isinstance(self.kind, DocumentChunkKind)
            or not isinstance(self.text, str)
            or not self.text.strip()
        ):
            raise ValueError("Chunk requires meaningful content")
        if (
            not isinstance(self.contributions, tuple)
            or not self.contributions
            or any(not isinstance(c, SourceContribution) for c in self.contributions)
        ):
            raise ValueError("Chunk requires ordered contributions")
        _validate_contribution_order(self.contributions)
        if (
            not isinstance(self.section_path, tuple)
            or len(self.section_path) > 6
            or any(type(i) is not int or i < 0 for i in self.section_path)
            or any(a >= b for a, b in zip(self.section_path, self.section_path[1:]))
            or (
                self.section_path
                and self.section_path[-1] > self.contributions[0].source_block_index
            )
        ):
            raise ValueError("Invalid chunk section path")
        for contribution in self.contributions:
            expected = (
                DocumentChunkKind.LIST
                if contribution.list_item is not None
                else DocumentChunkKind(contribution.kind.value)
            )
            if expected is not self.kind:
                raise ValueError("Incompatible chunk contribution")
            if contribution.quote_depth != self.contributions[0].quote_depth:
                raise ValueError("Incompatible quote context")

    @property
    def source_block_indexes(self) -> tuple[int, ...]:
        return tuple(dict.fromkeys(c.source_block_index for c in self.contributions))

    @property
    def page_numbers(self) -> tuple[int, ...]:
        return tuple(
            dict.fromkeys(
                c.page_number for c in self.contributions if c.page_number is not None
            )
        )


def _validate_contribution_order(contributions: tuple[SourceContribution, ...]) -> None:
    previous: SourceContribution | None = None
    uses_pages = contributions[0].page_number is not None
    for current in contributions:
        if (current.page_number is not None) != uses_pages:
            raise ValueError("Inconsistent chunk provenance")
        if previous is not None:
            if current.source_block_index < previous.source_block_index:
                raise ValueError("Invalid contribution order")
            if current.source_block_index == previous.source_block_index and (
                previous.text_end is None
                or current.text_start is None
                or previous.text_end != current.text_start
                or (
                    previous.kind,
                    previous.start_line,
                    previous.end_line,
                    previous.page_number,
                    previous.list_item,
                    previous.quote_depth,
                )
                != (
                    current.kind,
                    current.start_line,
                    current.end_line,
                    current.page_number,
                    current.list_item,
                    current.quote_depth,
                )
            ):
                raise ValueError("Invalid contribution slices")
            position = current.page_number if uses_pages else current.start_line
            previous_position = (
                previous.page_number if uses_pages else previous.start_line
            )
            assert position is not None and previous_position is not None
            if position < previous_position:
                raise ValueError("Invalid source provenance order")
        previous = current


@dataclass(frozen=True, repr=False)
class SegmentedDocument:
    source_file_public_id: UUID
    source_entity_tag: str
    extractor_id: str
    extractor_version: str
    normalizer_id: str
    normalizer_version: str
    segmenter_id: str
    segmenter_version: str
    preferred_chunk_bytes: int
    max_chunk_bytes: int
    max_source_contributions: int
    chunks: tuple[DocumentChunkCandidate, ...]
    page_count: int | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_file_public_id, UUID)
            or not self.source_file_public_id.int
        ):
            raise ValueError("Invalid source identity")
        for value in (
            self.source_entity_tag,
            self.extractor_id,
            self.extractor_version,
            self.normalizer_id,
            self.normalizer_version,
            self.segmenter_id,
            self.segmenter_version,
        ):
            if not isinstance(value, str) or not value.strip() or len(value) > 1024:
                raise ValueError("Invalid segmentation metadata")
        if (
            any(
                type(v) is not int or v < 1
                for v in (
                    self.preferred_chunk_bytes,
                    self.max_chunk_bytes,
                    self.max_source_contributions,
                )
            )
            or self.preferred_chunk_bytes > self.max_chunk_bytes
        ):
            raise ValueError("Invalid segmentation settings")
        if (
            not isinstance(self.chunks, tuple)
            or not self.chunks
            or any(not isinstance(c, DocumentChunkCandidate) for c in self.chunks)
        ):
            raise ValueError("Segmentation requires ordered chunks")
        uses_pages = self.chunks[0].contributions[0].page_number is not None
        if self.page_count is not None and (
            not uses_pages or type(self.page_count) is not int or self.page_count < 1
        ):
            raise ValueError("Invalid page count")
        previous: SourceContribution | None = None
        for index, chunk in enumerate(self.chunks):
            if (
                chunk.index != index
                or len(chunk.text.encode("utf-8")) > self.max_chunk_bytes
                or len(chunk.contributions) > self.max_source_contributions
            ):
                raise ValueError("Invalid chunk bounds or order")
            if (chunk.contributions[0].page_number is not None) != uses_pages:
                raise ValueError("Inconsistent segmentation provenance")
            if previous is not None:
                _validate_contribution_order((previous, chunk.contributions[0]))
            previous = chunk.contributions[-1]
            if self.page_count is not None and any(
                p > self.page_count for p in chunk.page_numbers
            ):
                raise ValueError("Page count excludes source pages")
