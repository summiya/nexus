import asyncio
from dataclasses import FrozenInstanceError, replace
from uuid import UUID

import pytest

from nexus.documents.application.normalize_document import NormalizeDocument
from nexus.documents.application.segment_document import (
    SEGMENTER_ID,
    SEGMENTER_VERSION,
    SegmentDocument,
)
from nexus.documents.domain.extracted_document import (
    ExtractedBlock,
    ExtractedDocument,
    ExtractedListItem,
)
from nexus.documents.domain.extracted_document import (
    ExtractedBlockKind as Kind,
)
from nexus.documents.domain.segmented_document import DocumentChunkKind as ChunkKind
from nexus.documents.ports.segmentation import (
    DocumentSegmentationError,
    DocumentSegmenter,
)
from nexus.documents.ports.segmentation import (
    DocumentSegmentationFailure as Failure,
)


def document(*specs, pages=None):
    blocks = []
    for index, spec in enumerate(specs):
        kind, text, *options = spec
        kwargs = options[0] if options else {}
        if pages is None:
            blocks.append(
                ExtractedBlock(index, kind, text, index + 1, index + 2, **kwargs)
            )
        else:
            blocks.append(
                ExtractedBlock(index, kind, text, page_number=pages[index], **kwargs)
            )
    return NormalizeDocument().execute(
        ExtractedDocument(
            UUID(int=1),
            "verified-etag",
            "nexus.test",
            "1",
            tuple(blocks),
            max(pages) + 1 if pages else None,
        )
    )


def small(**kwargs):
    return SegmentDocument(preferred_chunk_bytes=6, max_chunk_bytes=10, **kwargs)


def failure(segmenter, source, reason=Failure.RESOURCE_LIMIT):
    with pytest.raises(DocumentSegmentationError) as error:
        segmenter.execute(source)
    assert error.value.reason is reason
    assert str(error.value) == "Document segmentation failed"


def test_determinism_identity_versions_settings_and_immutability():
    source = document((Kind.PARAGRAPH, "first"), (Kind.PARAGRAPH, "second"))
    segmenter: DocumentSegmenter = small()
    result = segmenter.execute(source)
    assert result == segmenter.execute(source)
    assert [c.index for c in result.chunks] == [0, 1]
    assert result.source_file_public_id == source.source_file_public_id
    assert result.source_entity_tag == source.source_entity_tag
    assert (result.extractor_id, result.extractor_version) == (
        source.extractor_id,
        source.extractor_version,
    )
    assert (result.normalizer_id, result.normalizer_version) == (
        source.normalizer_id,
        source.normalizer_version,
    )
    assert (result.segmenter_id, result.segmenter_version) == (
        SEGMENTER_ID,
        SEGMENTER_VERSION,
    )
    assert (
        result.preferred_chunk_bytes,
        result.max_chunk_bytes,
        result.max_source_contributions,
    ) == (6, 10, 128)
    assert not hasattr(result, "max_chunks")
    assert "first" not in repr(result) + repr(result.chunks[0]) + repr(
        result.chunks[0].contributions[0]
    )
    for value, field in (
        (result, "chunks"),
        (result.chunks[0], "text"),
        (result.chunks[0].contributions[0], "start_line"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, None)


def test_preferred_target_crossed_by_whole_unit_and_separators_count():
    source = document(
        (Kind.PARAGRAPH, "a" * 3500),
        (Kind.PARAGRAPH, "b" * 1000),
        (Kind.PARAGRAPH, "c"),
    )
    chunks = SegmentDocument().execute(source).chunks
    assert [len(c.text.encode()) for c in chunks] == [4502, 1]
    assert chunks[0].source_block_indexes == (0, 1)
    assert chunks[0].text == "a" * 3500 + "\n\n" + "b" * 1000


def test_exact_hard_maximum_and_next_unit():
    source = document(
        (Kind.PARAGRAPH, "abc"), (Kind.PARAGRAPH, "defgh"), (Kind.PARAGRAPH, "i")
    )
    chunks = small().execute(source).chunks
    assert [c.text for c in chunks] == ["abc\n\ndefgh", "i"]
    assert all(c.contributions[0].text_start is None for c in chunks)


@pytest.mark.parametrize(
    "kind,separator", [(Kind.TEXT, "\n"), (Kind.PARAGRAPH, "\n\n")]
)
def test_same_structure_groups_and_preserves_line_provenance(kind, separator):
    (chunk,) = SegmentDocument().execute(document((kind, "a"), (kind, "b"))).chunks
    assert chunk.text == "a" + separator + "b"
    assert chunk.source_block_indexes == (0, 1)
    assert [(c.start_line, c.end_line) for c in chunk.contributions] == [(1, 2), (2, 3)]
    assert chunk.page_numbers == ()


def test_kind_quote_heading_and_blank_boundaries():
    source = document(
        (Kind.HEADING, "Architecture", {"heading_level": 1}),
        (Kind.HEADING, "Storage", {"heading_level": 2}),
        (Kind.PARAGRAPH, "a"),
        (Kind.PARAGRAPH, "b"),
        (Kind.PARAGRAPH, "quote", {"quote_depth": 1}),
        (Kind.TEXT, "line"),
        (Kind.TEXT, ""),
        (Kind.TEXT, "next"),
        (Kind.THEMATIC_BREAK, ""),
        (Kind.PARAGRAPH, "after"),
        (Kind.HEADING, "Other", {"heading_level": 1}),
        (Kind.PARAGRAPH, "last"),
    )
    chunks = SegmentDocument().execute(source).chunks
    assert [c.text for c in chunks] == [
        "a\n\nb",
        "quote",
        "line",
        "next",
        "after",
        "last",
    ]
    assert [c.section_path for c in chunks] == [(0, 1)] * 5 + [(10,)]
    assert chunks[1].contributions[0].quote_depth == 1
    assert all("Architecture" not in c.text and "Storage" not in c.text for c in chunks)
    assert source.blocks[0].text == "Architecture"


def test_heading_only_fallback_individual_ordered_headings_no_blank_heading():
    source = document(
        (Kind.HEADING, "first", {"heading_level": 1}),
        (Kind.HEADING, "", {"heading_level": 2}),
        (Kind.HEADING, "second", {"heading_level": 3}),
    )
    chunks = SegmentDocument().execute(source).chunks
    assert [c.text for c in chunks] == ["first", "second"]
    assert all(c.kind is ChunkKind.HEADING for c in chunks)
    assert [c.section_path for c in chunks] == [(0,), (0, 2)]
    assert [c.source_block_indexes for c in chunks] == [(0,), (2,)]


def test_empty_structural_content_fails_without_inventing_text():
    # A nonempty thematic marker can be meaningful to the upstream value contract.
    failure(SegmentDocument(), document((Kind.THEMATIC_BREAK, "---")), Failure.EMPTY)


def test_page_changes_do_not_force_boundaries_and_gaps_stay_exact():
    source = document(
        (Kind.PARAGRAPH, "a"),
        (Kind.PARAGRAPH, "b"),
        (Kind.PARAGRAPH, "c"),
        pages=(2, 4, 4),
    )
    result = SegmentDocument().execute(source)
    (chunk,) = result.chunks
    assert chunk.page_numbers == (2, 4)
    assert chunk.source_block_indexes == (0, 1, 2)
    assert result.page_count == 5
    assert all(c.start_line is None and c.end_line is None for c in chunk.contributions)


def item(list_line, item_line, depth=1, ordered=False, ordinal=None):
    return ExtractedListItem(list_line, item_line, depth, ordered, ordinal)


def test_small_nested_list_stays_whole_with_original_metadata():
    items = [item(1, 1), item(2, 2, 2, True, 1), item(1, 3)]
    source = document(
        *[
            (Kind.PARAGRAPH, str(i), {"list_item": value})
            for i, value in enumerate(items)
        ]
    )
    (chunk,) = SegmentDocument().execute(source).chunks
    assert chunk.kind is ChunkKind.LIST
    assert chunk.text == "0\n\n1\n\n2"
    assert [c.list_item for c in chunk.contributions] == items
    assert chunk.source_block_indexes == (0, 1, 2)


def test_separate_list_runs_and_prose_are_not_merged():
    source = document(
        (Kind.PARAGRAPH, "one", {"list_item": item(1, 1)}),
        (Kind.PARAGRAPH, "two", {"list_item": item(2, 2)}),
        (Kind.PARAGRAPH, "body"),
    )
    assert [c.text for c in SegmentDocument().execute(source).chunks] == [
        "one",
        "two",
        "body",
    ]


def test_oversized_list_prefers_item_boundaries_then_block_boundaries():
    source = document(
        (Kind.PARAGRAPH, "abc", {"list_item": item(1, 1)}),
        (Kind.PARAGRAPH, "def", {"list_item": item(1, 1)}),
        (Kind.PARAGRAPH, "ghij", {"list_item": item(1, 3)}),
    )
    assert [c.text for c in small().execute(source).chunks] == ["abc\n\ndef", "ghij"]
    source = document(
        (Kind.PARAGRAPH, "abcdef", {"list_item": item(1, 1)}),
        (Kind.CODE, "ghijkl", {"list_item": item(1, 1)}),
    )
    chunks = small().execute(source).chunks
    assert [c.text for c in chunks] == ["abcdef", "ghijkl"]
    assert all(c.kind is ChunkKind.LIST for c in chunks)
    assert chunks[1].contributions[0].kind is Kind.CODE


@pytest.mark.parametrize("kind", [Kind.CODE, Kind.RAW])
def test_code_raw_standalone_verbatim_and_newline_split(kind):
    text = "  a\t\n\nb  "
    source = document((kind, text), (kind, "next"), (Kind.PARAGRAPH, "body"))
    assert [c.text for c in SegmentDocument().execute(source).chunks] == [
        text,
        "next",
        "body",
    ]
    oversized = "abc\ndef\nghij"
    chunks = small().execute(document((kind, oversized))).chunks
    assert [c.text for c in chunks] == ["abc\ndef\n", "ghij"]
    assert "".join(c.text for c in chunks) == oversized


@pytest.mark.parametrize(
    "kind", [Kind.TEXT, Kind.PARAGRAPH, Kind.CODE, Kind.RAW, Kind.HEADING]
)
@pytest.mark.parametrize(
    "text", ["x" * 77, "é🙂界" * 20, "abc def ghi jkl mno", "abc\ndef\nghi\njkl\nmno"]
)
def test_hard_splits_reconstruct_exact_normalized_text_and_slices(kind, text):
    opts = {"heading_level": 1} if kind is Kind.HEADING else {}
    source = document((kind, text, opts))
    chunks = small().execute(source).chunks
    assert "".join(c.text for c in chunks) == source.blocks[0].text
    position = 0
    for chunk in chunks:
        (c,) = chunk.contributions
        assert c.source_block_index == 0
        assert c.text_start == position
        assert c.text_end > position
        assert chunk.text == source.blocks[0].text[c.text_start : c.text_end]
        assert (c.start_line, c.end_line) == (1, 2)
        assert len(chunk.text.encode()) <= 10 and chunk.text.strip()
        position = c.text_end
    assert position == len(source.blocks[0].text)


def test_oversized_list_block_keeps_item_and_slice_provenance():
    source = document((Kind.PARAGRAPH, "a" * 25, {"list_item": item(1, 1)}))
    chunks = small().execute(source).chunks
    assert [c.kind for c in chunks] == [ChunkKind.LIST] * 3
    assert all(c.contributions[0].list_item == item(1, 1) for c in chunks)
    assert "".join(c.text for c in chunks) == "a" * 25


def test_whitespace_boundary_attaches_to_meaningful_piece_without_loss():
    source = document((Kind.CODE, "ab\n  cd\n   "))
    chunks = (
        SegmentDocument(preferred_chunk_bytes=5, max_chunk_bytes=6)
        .execute(source)
        .chunks
    )
    assert "".join(c.text for c in chunks) == source.blocks[0].text
    assert all(c.text.strip() and len(c.text.encode()) <= 6 for c in chunks)


@pytest.mark.parametrize(
    "text", ["a" + " " * 30, " " * 30 + "a", "a\n" + " " * 30 + "b"]
)
def test_impossible_whitespace_preservation_fails_safely(text):
    failure(small(), document((Kind.CODE, text)))


def test_single_code_point_larger_than_hard_bound_fails_safely():
    failure(
        SegmentDocument(preferred_chunk_bytes=1, max_chunk_bytes=1),
        document((Kind.TEXT, "🙂")),
    )


@pytest.mark.parametrize(
    "name",
    [
        "preferred_chunk_bytes",
        "max_chunk_bytes",
        "max_source_contributions",
        "max_input_blocks",
        "max_input_bytes",
        "max_output_bytes",
        "max_chunks",
    ],
)
@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, "10", None])
def test_invalid_configuration_types_and_values(name, value):
    with pytest.raises(ValueError, match="Invalid segmentation limits"):
        SegmentDocument(**{name: value})


def test_preferred_cannot_exceed_hard_bound():
    with pytest.raises(ValueError):
        SegmentDocument(preferred_chunk_bytes=11, max_chunk_bytes=10)


@pytest.mark.parametrize(
    "limits",
    [
        {"max_input_blocks": 1},
        {"max_input_bytes": 3},
        {"max_output_bytes": 5},
        {"max_chunks": 1},
    ],
)
def test_operational_bounds_fail_without_partial_result(limits):
    source = document((Kind.TEXT, "abc"), (Kind.PARAGRAPH, "def"))
    failure(SegmentDocument(**limits), source)


def test_separators_count_toward_output_bound():
    source = document((Kind.PARAGRAPH, "a"), (Kind.PARAGRAPH, "b"))
    failure(SegmentDocument(max_output_bytes=3), source)
    assert (
        SegmentDocument(max_output_bytes=4).execute(source).chunks[0].text == "a\n\nb"
    )


def test_contribution_bound_changes_layout_deterministically():
    source = document(*[(Kind.TEXT, "a") for _ in range(9)])
    result = SegmentDocument(max_source_contributions=2).execute(source)
    assert [c.source_block_indexes for c in result.chunks] == [
        (0, 1),
        (2, 3),
        (4, 5),
        (6, 7),
        (8,),
    ]
    assert result.max_source_contributions == 2


def test_contribution_bound_splits_list_at_existing_blocks():
    source = document(
        *[(Kind.PARAGRAPH, "a", {"list_item": item(1, 1)}) for _ in range(5)]
    )
    chunks = SegmentDocument(max_source_contributions=2).execute(source).chunks
    assert [len(c.contributions) for c in chunks] == [2, 2, 1]
    assert all(c.kind is ChunkKind.LIST for c in chunks)


def test_thousands_of_tiny_blocks_have_bounded_ordered_output():
    source = document(*[(Kind.TEXT, "a") for _ in range(5000)])
    result = SegmentDocument().execute(source)
    assert len(result.chunks) == 40
    assert tuple(i for c in result.chunks for i in c.source_block_indexes) == tuple(
        range(5000)
    )
    assert all(len(c.contributions) <= 128 for c in result.chunks)


def test_huge_unbroken_unit_and_chunk_bound():
    source = document((Kind.CODE, "界" * 100_000))
    result = SegmentDocument().execute(source)
    assert "".join(c.text for c in result.chunks) == source.blocks[0].text
    failure(SegmentDocument(max_chunks=1), source)


def test_operational_guards_do_not_change_successful_result():
    source = document((Kind.TEXT, "a"), (Kind.TEXT, "b"))
    assert SegmentDocument().execute(source) == SegmentDocument(
        max_chunks=1, max_input_blocks=2, max_input_bytes=2, max_output_bytes=3
    ).execute(source)


def test_markdown_extraction_normalization_segmentation():
    from nexus.documents.ports.source import DocumentSource
    from nexus.infrastructure.extraction.text import MarkdownDocumentExtractor

    data = b"# Title\n\nFirst paragraph.\n\nSecond paragraph.\n\n- alpha\n- beta\n"

    async def stream():
        yield data

    # This test uses the existing verified-source boundary, not another reader.
    source = DocumentSource(
        UUID(int=1), "notes.md", "text/markdown", "etag", len(data), stream()
    )
    normalized = NormalizeDocument().execute(
        asyncio.run(MarkdownDocumentExtractor().extract(source))
    )
    result = SegmentDocument().execute(normalized)
    assert [c.text for c in result.chunks] == [
        "First paragraph.\n\nSecond paragraph.",
        "alpha\n\nbeta",
    ]
    assert all(c.section_path == (0,) for c in result.chunks)
    assert result.chunks[1].kind is ChunkKind.LIST


def test_whitespace_attaches_to_following_piece_when_preceding_piece_is_full():
    source = document((Kind.CODE, "aaaa     b"))
    chunks = (
        SegmentDocument(preferred_chunk_bytes=4, max_chunk_bytes=4)
        .execute(source)
        .chunks
    )
    assert "".join(c.text for c in chunks) == source.blocks[0].text
    assert all(c.text.strip() and len(c.text.encode()) <= 4 for c in chunks)


@pytest.mark.parametrize("text", ["a\n a   ", "aaaa a   ", "aaaa     b"])
def test_whitespace_redistribution_keeps_every_piece_meaningful(text):
    source = document((Kind.CODE, text))
    chunks = (
        SegmentDocument(preferred_chunk_bytes=4, max_chunk_bytes=4)
        .execute(source)
        .chunks
    )
    assert "".join(c.text for c in chunks) == source.blocks[0].text
    assert all(c.text.strip() and len(c.text.encode()) <= 4 for c in chunks)


def test_hard_splitting_uses_bounded_forward_scans():
    class CountedText(str):
        inspected = 0

        def __getitem__(self, key):
            result = super().__getitem__(key)
            self.inspected += len(result)
            return result

    source = document((Kind.CODE, "a\n" + "x" * 100_000))
    text = CountedText(source.blocks[0].text)
    source = replace(source, blocks=(replace(source.blocks[0], text=text),))
    result = SegmentDocument(preferred_chunk_bytes=512, max_chunk_bytes=1024).execute(
        source
    )
    assert "".join(c.text for c in result.chunks) == text
    assert text.inspected < 10 * len(text)
