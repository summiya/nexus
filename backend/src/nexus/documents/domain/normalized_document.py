"""Immutable canonical content and its small object-storage reference."""

from dataclasses import dataclass
from uuid import UUID

from nexus.documents.domain.extracted_document import (
    ExtractedBlock,
    ExtractedBlockKind,
    ExtractedDocument,
    ExtractedListItem,
)


@dataclass(frozen=True, repr=False)
class NormalizedBlock:
    source_block_index: int
    kind: ExtractedBlockKind
    text: str
    start_line: int | None = None
    end_line: int | None = None
    heading_level: int | None = None
    list_item: ExtractedListItem | None = None
    quote_depth: int = 0
    page_number: int | None = None
    section_path: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        _extracted_block(self)  # Reuse the existing kind/provenance invariants.
        if (
            not isinstance(self.section_path, tuple)
            or len(self.section_path) > 6
            or any(
                type(index) is not int or not 0 <= index <= self.source_block_index
                for index in self.section_path
            )
        ):
            raise ValueError("Invalid section path")


def _extracted_block(block: NormalizedBlock) -> ExtractedBlock:
    return ExtractedBlock(
        block.source_block_index,
        block.kind,
        block.text,
        block.start_line,
        block.end_line,
        block.heading_level,
        block.list_item,
        block.quote_depth,
        block.page_number,
    )


@dataclass(frozen=True, repr=False)
class NormalizedDocument:
    source_file_public_id: UUID
    source_entity_tag: str
    extractor_id: str
    extractor_version: str
    normalizer_id: str
    normalizer_version: str
    blocks: tuple[NormalizedBlock, ...]
    page_count: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.blocks, tuple) or not all(
            isinstance(block, NormalizedBlock) for block in self.blocks
        ):
            raise ValueError("Normalization requires ordered blocks")
        ExtractedDocument(
            self.source_file_public_id,
            self.source_entity_tag,
            self.extractor_id,
            self.extractor_version,
            tuple(_extracted_block(block) for block in self.blocks),
            self.page_count,
        )
        _require_metadata(self.normalizer_id, self.normalizer_version)
        # Inspect each heading's text once, even when many blocks reference it.
        heading_levels = {
            block.source_block_index: block.heading_level
            for block in self.blocks
            if block.kind is ExtractedBlockKind.HEADING and block.text.strip()
        }
        for block in self.blocks:
            previous_index = -1
            previous_level = 0
            for index in block.section_path:
                level = heading_levels.get(index)
                if (
                    level is None
                    or index <= previous_index
                    or level <= previous_level
                ):
                    raise ValueError(
                        "Section path requires ordered meaningful headings"
                    )
                previous_index = index
                previous_level = level


def _require_metadata(*values: str) -> None:
    if any(
        not isinstance(value, str) or not value.strip() or len(value) > 1024
        for value in values
    ):
        raise ValueError("Invalid normalization metadata")


@dataclass(frozen=True, repr=False)
class NormalizedArtifactReference:
    organization_public_id: UUID
    source_file_public_id: UUID
    source_entity_tag: str
    storage_key: str
    checksum_sha256: str
    size_bytes: int
    schema_version: int
    extractor_id: str
    extractor_version: str
    normalizer_id: str
    normalizer_version: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, UUID) or not value.int
            for value in (self.organization_public_id, self.source_file_public_id)
        ):
            raise ValueError("Invalid artifact identity")
        _require_metadata(
            self.source_entity_tag,
            self.storage_key,
            self.extractor_id,
            self.extractor_version,
            self.normalizer_id,
            self.normalizer_version,
        )
        if (
            not isinstance(self.checksum_sha256, str)
            or len(self.checksum_sha256) != 64
            or any(char not in "0123456789abcdef" for char in self.checksum_sha256)
            or type(self.size_bytes) is not int
            or self.size_bytes < 1
            or type(self.schema_version) is not int
            or self.schema_version < 1
        ):
            raise ValueError("Invalid artifact integrity metadata")
