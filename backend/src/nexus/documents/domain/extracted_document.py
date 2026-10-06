"""Ordered extraction values with source lines or one-based PDF pages."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class ExtractedBlockKind(StrEnum):
    TEXT = "text"
    PARAGRAPH = "paragraph"
    HEADING = "heading"
    CODE = "code"
    RAW = "raw"
    THEMATIC_BREAK = "thematic_break"


@dataclass(frozen=True)
class ExtractedListItem:
    """Identify an observed list and item without introducing container blocks."""

    list_start_line: int
    item_start_line: int
    depth: int
    ordered: bool
    ordinal: int | None = None

    def __post_init__(self) -> None:
        if (
            any(
                type(value) is not int
                for value in (self.list_start_line, self.item_start_line, self.depth)
            )
            or not 1 <= self.list_start_line <= self.item_start_line
            or self.depth < 1
        ):
            raise ValueError("Invalid list provenance")
        if (
            type(self.ordered) is not bool
            or (self.ordinal is not None and type(self.ordinal) is not int)
            or self.ordered != (self.ordinal is not None)
        ):
            raise ValueError("Invalid list ordinal")


@dataclass(frozen=True, repr=False)
class ExtractedBlock:
    index: int
    kind: ExtractedBlockKind
    text: str
    start_line: int | None = None
    end_line: int | None = None
    heading_level: int | None = None
    list_item: ExtractedListItem | None = None
    quote_depth: int = 0
    page_number: int | None = None

    def __post_init__(self) -> None:
        if type(self.index) is not int or self.index < 0:
            raise ValueError("Invalid block order")
        if self.page_number is None:
            if (
                type(self.start_line) is not int
                or type(self.end_line) is not int
                or not 1 <= self.start_line < self.end_line
            ):
                raise ValueError("Invalid line provenance")
        elif (
            type(self.page_number) is not int
            or self.page_number < 1
            or self.start_line is not None
            or self.end_line is not None
            or self.list_item is not None
            or self.quote_depth != 0
        ):
            raise ValueError("Invalid page provenance")
        if (
            not isinstance(self.kind, ExtractedBlockKind)
            or not isinstance(self.text, str)
            or type(self.quote_depth) is not int
            or self.quote_depth < 0
        ):
            raise ValueError("Invalid block kind, text, or quote depth")
        if self.kind is ExtractedBlockKind.HEADING:
            if self.heading_level is None or not 1 <= self.heading_level <= 6:
                raise ValueError("Invalid heading level")
        elif self.heading_level is not None:
            raise ValueError("Heading level requires a heading")


@dataclass(frozen=True, repr=False)
class ExtractedDocument:
    source_file_public_id: UUID
    source_entity_tag: str
    extractor_id: str
    extractor_version: str
    blocks: tuple[ExtractedBlock, ...]

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
        ):
            if not isinstance(value, str) or not value.strip() or len(value) > 1024:
                raise ValueError("Invalid extraction metadata")
        if not isinstance(self.blocks, tuple) or not self.blocks:
            raise ValueError("Extraction requires ordered blocks")
        uses_pages = self.blocks[0].page_number is not None
        previous_position = 1
        for index, block in enumerate(self.blocks):
            if (block.page_number is not None) != uses_pages:
                raise ValueError("Extraction requires consistent provenance")
            position = block.page_number if uses_pages else block.start_line
            if position is None or block.index != index or position < previous_position:
                raise ValueError("Invalid extraction order")
            previous_position = position
        if not any(block.text.strip() for block in self.blocks):
            raise ValueError("Extraction requires meaningful content")
