"""Deterministic structure-first segmentation of authoritative normalized blocks."""

from collections.abc import Iterator, Sequence

from nexus.documents.domain.extracted_document import ExtractedBlockKind as Kind
from nexus.documents.domain.normalized_document import (
    NormalizedBlock,
    NormalizedDocument,
)
from nexus.documents.domain.segmented_document import (
    DocumentChunkCandidate,
    DocumentChunkKind,
    SegmentedDocument,
    SourceContribution,
)
from nexus.documents.ports.segmentation import (
    DocumentSegmentationError,
    DocumentSegmentationFailure,
)

SEGMENTER_ID = "nexus.structure"
SEGMENTER_VERSION = "1"


def _resource_limit() -> DocumentSegmentationError:
    return DocumentSegmentationError(DocumentSegmentationFailure.RESOURCE_LIMIT)


def _text_bytes(text: str, maximum: int) -> int:
    size = 0
    for start in range(0, len(text), 8192):
        size += len(text[start : start + 8192].encode("utf-8"))
        if size > maximum:
            raise _resource_limit()
    return size


def _kind(block: NormalizedBlock) -> DocumentChunkKind:
    return (
        DocumentChunkKind.LIST
        if block.list_item is not None
        else DocumentChunkKind(block.kind.value)
    )


def _contribution(
    block: NormalizedBlock, start: int | None = None, end: int | None = None
) -> SourceContribution:
    return SourceContribution(
        block.source_block_index,
        block.kind,
        block.start_line,
        block.end_line,
        block.page_number,
        block.list_item,
        block.quote_depth,
        start,
        end,
    )


def _groups(blocks: Sequence[NormalizedBlock]) -> Iterator[list[NormalizedBlock]]:
    """Contiguous observed structures; blanks and headings are boundaries."""
    group: list[NormalizedBlock] = []
    for block in blocks:
        if block.kind in (Kind.HEADING, Kind.THEMATIC_BREAK) or not block.text.strip():
            if group:
                yield group
                group = []
            continue
        compatible = False
        if group:
            first = group[0]
            compatible = (
                first.section_path == block.section_path
                and first.quote_depth == block.quote_depth
            )
            if first.list_item is not None and block.list_item is not None:
                root, item = first.list_item, block.list_item
                compatible = compatible and (
                    item.depth > root.depth
                    or (
                        item.depth == root.depth
                        and item.list_start_line == root.list_start_line
                        and item.ordered == root.ordered
                    )
                )
            else:
                compatible = (
                    compatible
                    and first.list_item is None
                    and block.list_item is None
                    and first.kind == block.kind
                    and block.kind in (Kind.TEXT, Kind.PARAGRAPH)
                )
        if group and not compatible:
            yield group
            group = []
        group.append(block)
    if group:
        yield group


def _units(
    group: list[NormalizedBlock], sizes: list[int], maximum: int, max_contributions: int
) -> Iterator[list[NormalizedBlock]]:
    """A fitting list stays whole; otherwise prefer observed item/block boundaries."""
    if group[0].list_item is None:
        for block in group:
            yield [block]
        return
    size = sum(sizes[b.source_block_index] for b in group) + 2 * (len(group) - 1)
    if size <= maximum and len(group) <= max_contributions:
        yield group
        return
    start = 0
    while start < len(group):
        end = start + 1
        while end < len(group) and group[end].list_item == group[start].list_item:
            end += 1
        item = group[start:end]
        size = sum(sizes[b.source_block_index] for b in item) + 2 * (len(item) - 1)
        if size <= maximum and len(item) <= max_contributions:
            yield item
        else:
            for block in item:
                yield [block]
        start = end


def _whitespace_end(text: str, start: int, end: int, available_bytes: int) -> int:
    """Find how much adjacent whitespace fits without copying or stripping it."""
    while start < end and text[start].isspace():
        width = len(text[start].encode("utf-8"))
        if width > available_bytes:
            break
        available_bytes -= width
        start += 1
    return start


def _slices(
    text: str, maximum: int, *, word_boundaries: bool
) -> Iterator[tuple[int, int]]:
    """Bounded forward scans, retaining delimiters and exact normalized offsets."""
    start = 0
    pending: tuple[int, int] | None = None
    while start < len(text):
        end = start
        size = 0
        newline = whitespace = 0
        while end < len(text):
            char = text[end]
            width = len(char.encode("utf-8"))
            if size + width > maximum:
                break
            size += width
            end += 1
            if char == "\n":
                newline = end
            if char.isspace():
                whitespace = end
        if end == start:
            raise _resource_limit()
        boundary = (
            end
            if end == len(text)
            else newline or (whitespace if word_boundaries else 0) or end
        )
        # A leading blank boundary may be avoidable within this same window.
        if not text[start:boundary].strip() and text[start:end].strip():
            boundary = end
        if not text[boundary:end].strip():
            boundary = end  # Keep nearby whitespace with the current content.
        if not text[start:boundary].strip():
            if pending is None:
                raise _resource_limit()
            combined = text[pending[0] : boundary]
            if len(combined.encode("utf-8")) <= maximum:
                pending = (pending[0], boundary)
            else:
                # Reserve the last meaningful code point for the blank tail.
                split = pending[1] - 1
                while split >= pending[0] and text[split].isspace():
                    split -= 1
                if split <= pending[0] or not text[pending[0] : split].strip():
                    # A single remaining anchor still has room for part of the run.
                    # Keep it until the following meaningful piece can take the rest.
                    split = pending[0]
                remaining = maximum - len(text[split:start].encode("utf-8"))
                attached = _whitespace_end(text, start, boundary, remaining)
                if attached == start:
                    raise _resource_limit()
                if split > pending[0]:
                    yield pending[0], split
                pending = (split, attached)
                boundary = attached
        else:
            if pending is not None:
                # Give leading whitespace to the preceding piece when it fits.
                remaining = maximum - len(text[pending[0] : pending[1]].encode("utf-8"))
                start = _whitespace_end(text, start, boundary, remaining)
                if start < boundary and text[start].isspace():
                    split = pending[1] - 1
                    while split >= pending[0] and text[split].isspace():
                        split -= 1
                    if split > pending[0] and text[pending[0] : split].strip():
                        yield pending[0], split
                        remaining = maximum - len(text[split:start].encode("utf-8"))
                        start = _whitespace_end(text, start, boundary, remaining)
                        pending = (split, start)
                yield pending[0], start
            pending = (start, boundary)
        start = boundary
    if pending is not None:
        yield pending


class SegmentDocument:
    def __init__(
        self,
        *,
        preferred_chunk_bytes: int = 4 * 1024,
        max_chunk_bytes: int = 8 * 1024,
        max_source_contributions: int = 128,
        max_input_blocks: int = 50_000,
        max_input_bytes: int = 8 * 1024 * 1024,
        max_output_bytes: int = 16 * 1024 * 1024,
        max_chunks: int = 10_000,
    ) -> None:
        if (
            any(
                type(v) is not int or v < 1
                for v in (
                    preferred_chunk_bytes,
                    max_chunk_bytes,
                    max_source_contributions,
                    max_input_blocks,
                    max_input_bytes,
                    max_output_bytes,
                    max_chunks,
                )
            )
            or preferred_chunk_bytes > max_chunk_bytes
        ):
            raise ValueError("Invalid segmentation limits")
        self._preferred = preferred_chunk_bytes
        self._maximum = max_chunk_bytes
        self._max_contributions = max_source_contributions
        self._max_input_blocks = max_input_blocks
        self._max_input_bytes = max_input_bytes
        self._max_output_bytes = max_output_bytes
        self._max_chunks = max_chunks

    def execute(self, document: NormalizedDocument) -> SegmentedDocument:
        if len(document.blocks) > self._max_input_blocks:
            raise _resource_limit()
        sizes: list[int] = []
        input_bytes = 0
        for block in document.blocks:
            size = _text_bytes(block.text, self._max_input_bytes - input_bytes)
            sizes.append(size)
            input_bytes += size
        chunks: list[DocumentChunkCandidate] = []
        output_bytes = 0

        def emit(
            text: str,
            blocks: Sequence[NormalizedBlock],
            size: int,
            *,
            start: int | None = None,
            end: int | None = None,
        ) -> None:
            nonlocal output_bytes
            if (
                len(chunks) >= self._max_chunks
                or output_bytes + size > self._max_output_bytes
            ):
                raise _resource_limit()
            contributions = tuple(_contribution(b, start, end) for b in blocks)
            chunks.append(
                DocumentChunkCandidate(
                    len(chunks),
                    _kind(blocks[0]),
                    text,
                    blocks[0].section_path,
                    contributions,
                )
            )
            output_bytes += size

        def segment_group(group: list[NormalizedBlock]) -> None:
            separator = "\n" if _kind(group[0]) is DocumentChunkKind.TEXT else "\n\n"
            pending: list[NormalizedBlock] = []
            pending_bytes = 0

            def flush() -> None:
                nonlocal pending, pending_bytes
                if pending:
                    emit(
                        separator.join(b.text for b in pending), pending, pending_bytes
                    )
                    pending = []
                    pending_bytes = 0

            for unit in _units(group, sizes, self._maximum, self._max_contributions):
                unit_bytes = sum(sizes[b.source_block_index] for b in unit) + len(
                    separator
                ) * (len(unit) - 1)
                if unit_bytes > self._maximum:
                    flush()
                    assert len(unit) == 1
                    block = unit[0]
                    for start, end in _slices(
                        block.text,
                        self._maximum,
                        word_boundaries=block.kind not in (Kind.CODE, Kind.RAW),
                    ):
                        text = block.text[start:end]
                        emit(
                            text, unit, len(text.encode("utf-8")), start=start, end=end
                        )
                    continue
                added_bytes = unit_bytes + (len(separator) if pending else 0)
                if pending and (
                    pending_bytes >= self._preferred
                    or pending_bytes + added_bytes > self._maximum
                    or len(pending) + len(unit) > self._max_contributions
                ):
                    flush()
                    added_bytes = unit_bytes
                pending.extend(unit)
                pending_bytes += added_bytes
            flush()

        for group in _groups(document.blocks):
            segment_group(group)
        if not chunks:
            for block in document.blocks:
                if block.kind is Kind.HEADING and block.text.strip():
                    segment_group([block])
        if not chunks:
            raise DocumentSegmentationError(DocumentSegmentationFailure.EMPTY)
        return SegmentedDocument(
            document.source_file_public_id,
            document.source_entity_tag,
            document.extractor_id,
            document.extractor_version,
            document.normalizer_id,
            document.normalizer_version,
            SEGMENTER_ID,
            SEGMENTER_VERSION,
            self._preferred,
            self._maximum,
            self._max_contributions,
            tuple(chunks),
            document.page_count,
        )
