"""Ordered extraction values; source lines are one-based and end-exclusive."""

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
        if not 1 <= self.list_start_line <= self.item_start_line or self.depth < 1:
            raise ValueError("Invalid list provenance")
        if self.ordered != (self.ordinal is not None):
            raise ValueError("Invalid list ordinal")


@dataclass(frozen=True, repr=False)
class ExtractedBlock:
    index: int
    kind: ExtractedBlockKind
    text: str
    start_line: int
    end_line: int
    heading_level: int | None = None
    list_item: ExtractedListItem | None = None
    quote_depth: int = 0

    def __post_init__(self) -> None:
        if self.index < 0 or not 1 <= self.start_line < self.end_line:
            raise ValueError("Invalid block order or provenance")
        if not isinstance(self.kind, ExtractedBlockKind) or self.quote_depth < 0:
            raise ValueError("Invalid block kind or quote depth")
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
            if not value.strip() or len(value) > 1024:
                raise ValueError("Invalid extraction metadata")
        if not isinstance(self.blocks, tuple) or not self.blocks:
            raise ValueError("Extraction requires ordered blocks")
        previous_line = 1
        for index, block in enumerate(self.blocks):
            if block.index != index or block.start_line < previous_line:
                raise ValueError("Invalid extraction order")
            previous_line = block.start_line
        if not any(block.text.strip() for block in self.blocks):
            raise ValueError("Extraction requires meaningful content")
