from dataclasses import FrozenInstanceError, replace
from uuid import UUID

import pytest

from nexus.documents.domain.extracted_document import ExtractedBlockKind as Kind
from nexus.documents.domain.segmented_document import (
    DocumentChunkCandidate,
    DocumentChunkKind,
    SegmentedDocument,
    SourceContribution,
)


def contribution(**kwargs):
    return SourceContribution(0, Kind.TEXT, 1, 2, **kwargs)


def chunk(**kwargs):
    fields = {
        "index": 0,
        "kind": DocumentChunkKind.TEXT,
        "text": "content",
        "section_path": (),
        "contributions": (contribution(),),
    }
    return DocumentChunkCandidate(**(fields | kwargs))


def segmented(**kwargs):
    fields = {
        "source_file_public_id": UUID(int=1),
        "source_entity_tag": "etag",
        "extractor_id": "txt",
        "extractor_version": "1",
        "normalizer_id": "normalizer",
        "normalizer_version": "1",
        "segmenter_id": "segmenter",
        "segmenter_version": "1",
        "preferred_chunk_bytes": 10,
        "max_chunk_bytes": 20,
        "max_source_contributions": 2,
        "chunks": (chunk(),),
    }
    return SegmentedDocument(**(fields | kwargs))


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_block_index", True),
        ("source_block_index", -1),
        ("start_line", True),
        ("end_line", 1),
        ("end_line", "2"),
        ("quote_depth", True),
        ("quote_depth", -1),
        ("kind", "text"),
        ("list_item", "item"),
        ("text_start", True),
        ("text_end", 1),
    ],
)
def test_invalid_contribution_types_and_ranges(field, value):
    with pytest.raises(ValueError):
        replace(contribution(), **{field: value})


@pytest.mark.parametrize(
    "start,end", [(None, 2), (1, None), (1, 1), (-1, 2), (True, 2), (0, False)]
)
def test_invalid_normalized_slices(start, end):
    with pytest.raises(ValueError):
        contribution(text_start=start, text_end=end)


def test_valid_normalized_slice_and_immutable_contribution():
    value = contribution(text_start=0, text_end=2)
    assert (value.text_start, value.text_end) == (0, 2)
    with pytest.raises(FrozenInstanceError):
        value.text_start = 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("index", True),
        ("index", -1),
        ("text", 1),
        ("text", " "),
        ("kind", "text"),
        ("contributions", []),
        ("contributions", ()),
        ("contributions", (None,)),
        ("section_path", []),
        ("section_path", (True,)),
        ("section_path", (-1,)),
        ("section_path", (0, 0)),
        ("section_path", (1,)),
    ],
)
def test_invalid_chunk_values(field, value):
    with pytest.raises(ValueError):
        chunk(**{field: value})


def test_invalid_order_provenance_kind_and_context():
    first = contribution()
    later = SourceContribution(1, Kind.TEXT, 2, 3)
    for contributions in (
        (later, first),
        (first, first),
        (first, SourceContribution(1, Kind.TEXT, page_number=2)),
        (later, SourceContribution(2, Kind.TEXT, 1, 2)),
        (first, SourceContribution(1, Kind.PARAGRAPH, 2, 3)),
        (first, SourceContribution(1, Kind.TEXT, 2, 3, quote_depth=1)),
    ):
        with pytest.raises(ValueError):
            chunk(contributions=contributions)


def test_slices_require_contiguous_nonoverlapping_order():
    first = contribution(text_start=0, text_end=2)
    second = contribution(text_start=2, text_end=4)
    assert chunk(contributions=(first, second)).source_block_indexes == (0,)
    for start in (1, 3):
        with pytest.raises(ValueError):
            chunk(contributions=(first, replace(second, text_start=start)))


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_file_public_id", UUID(int=0)),
        ("source_file_public_id", "id"),
        ("source_entity_tag", True),
        ("extractor_id", " "),
        ("extractor_version", "x" * 1025),
        ("normalizer_id", None),
        ("normalizer_version", 1),
        ("segmenter_id", ""),
        ("segmenter_version", True),
        ("preferred_chunk_bytes", True),
        ("max_chunk_bytes", 0),
        ("max_source_contributions", -1),
        ("chunks", []),
        ("chunks", ()),
        ("chunks", (None,)),
        ("page_count", 2),
    ],
)
def test_invalid_document_metadata(field, value):
    with pytest.raises(ValueError):
        segmented(**{field: value})


def test_document_bounds_and_cross_chunk_order():
    for kwargs in (
        {"preferred_chunk_bytes": 21},
        {"max_chunk_bytes": 5, "preferred_chunk_bytes": 5},
        {"chunks": (chunk(index=1),)},
        {"chunks": (chunk(), chunk(index=1))},
        {
            "max_source_contributions": 1,
            "chunks": (
                chunk(
                    contributions=(
                        contribution(),
                        SourceContribution(1, Kind.TEXT, 2, 3),
                    )
                ),
            ),
        },
    ):
        with pytest.raises(ValueError):
            segmented(**kwargs)


def test_page_gaps_derived_and_count_validated():
    values = (
        SourceContribution(0, Kind.TEXT, page_number=2),
        SourceContribution(1, Kind.TEXT, page_number=4),
        SourceContribution(2, Kind.TEXT, page_number=4),
    )
    value = chunk(contributions=values)
    assert value.page_numbers == (2, 4)
    assert value.source_block_indexes == (0, 1, 2)
    result = segmented(chunks=(value,), max_source_contributions=3, page_count=5)
    for count in (True, 0, 3):
        with pytest.raises(ValueError):
            replace(result, page_count=count)
    assert replace(result, page_count=None).chunks == result.chunks


def test_result_and_chunks_are_immutable():
    value = segmented()
    with pytest.raises(FrozenInstanceError):
        value.chunks = ()
    with pytest.raises(FrozenInstanceError):
        value.chunks[0].text = "changed"


def test_same_source_block_slices_cannot_change_provenance():
    first = contribution(text_start=0, text_end=2)
    second = contribution(text_start=2, text_end=4)
    with pytest.raises(ValueError):
        chunk(contributions=(first, replace(second, end_line=3)))
