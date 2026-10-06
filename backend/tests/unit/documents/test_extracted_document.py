from dataclasses import FrozenInstanceError, replace
from uuid import UUID

import pytest

from nexus.documents.domain import (
    ExtractedBlock,
    ExtractedDocument,
    ExtractedListItem,
)
from nexus.documents.domain import (
    ExtractedBlockKind as Kind,
)


def block(**kwargs):
    return replace(ExtractedBlock(0, Kind.TEXT, "content", 1, 2), **kwargs)


def document(**kwargs):
    return replace(
        ExtractedDocument(UUID(int=1), "etag", "nexus.txt", "1", (block(),)), **kwargs
    )


def test_extracted_values_are_immutable_and_do_not_repr_private_content():
    value = document()
    assert "content" not in repr(value) and "content" not in repr(value.blocks[0])
    with pytest.raises(FrozenInstanceError):
        value.extractor_version = "2"
    assert (
        document(blocks=(block(text=" "), block(index=1, start_line=2, end_line=3)))
        .blocks[0]
        .text
        == " "
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"index": -1},
        {"start_line": 0},
        {"end_line": 1},
        {"kind": "text"},
        {"quote_depth": -1},
        {"heading_level": 1},
        {"kind": Kind.HEADING},
        {"kind": Kind.HEADING, "heading_level": 7},
    ],
)
def test_invalid_block_order_provenance_or_metadata_is_rejected(kwargs):
    with pytest.raises(ValueError):
        block(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"source_file_public_id": UUID(int=0)},
        {"source_entity_tag": ""},
        {"extractor_id": " "},
        {"extractor_version": "v" * 1025},
        {"blocks": ()},
        {"blocks": [block()]},
        {"blocks": (block(index=1),)},
        {"blocks": (block(text=" "),)},
        {
            "blocks": (
                block(start_line=3, end_line=4),
                block(index=1, start_line=2, end_line=3),
            )
        },
    ],
)
def test_invalid_extracted_document_is_rejected(kwargs):
    with pytest.raises(ValueError):
        document(**kwargs)


@pytest.mark.parametrize(
    "args",
    [
        (0, 1, 1, False, None),
        (2, 1, 1, False, None),
        (1, 1, 0, False, None),
        (1, 1, 1, True, None),
        (1, 1, 1, False, 1),
    ],
)
def test_invalid_list_metadata_is_rejected(args):
    with pytest.raises(ValueError):
        ExtractedListItem(*args)


@pytest.mark.parametrize("field", ["index", "start_line", "end_line", "quote_depth"])
@pytest.mark.parametrize("value", [True, False, 2.0, "2", None])
def test_block_integer_fields_reject_invalid_types(field, value):
    with pytest.raises(ValueError):
        block(**{field: value})


@pytest.mark.parametrize("field", ["list_start_line", "item_start_line", "depth"])
@pytest.mark.parametrize("value", [True, False, 1.0, "1", None])
def test_list_integer_fields_reject_invalid_types(field, value):
    with pytest.raises(ValueError):
        replace(ExtractedListItem(1, 1, 1, False), **{field: value})


@pytest.mark.parametrize("value", [0, 1, 0.0, 1.0, "ordered", None])
def test_list_ordered_requires_a_bool(value):
    with pytest.raises(ValueError):
        ExtractedListItem(1, 1, 1, value, 1 if value else None)


@pytest.mark.parametrize("value", [True, False, 1.0, "1", b"1"])
def test_list_ordinal_rejects_non_integer_types(value):
    with pytest.raises(ValueError):
        ExtractedListItem(1, 1, 1, True, value)


@pytest.mark.parametrize("value", [None, True, 1, 1.0, b"text", ["text"]])
def test_block_text_requires_a_string(value):
    with pytest.raises(ValueError):
        block(text=value)


@pytest.mark.parametrize(
    "field", ["source_entity_tag", "extractor_id", "extractor_version"]
)
@pytest.mark.parametrize("value", [None, True, 1, 1.0, b"value", ["value"]])
def test_extraction_metadata_requires_strings(field, value):
    with pytest.raises(ValueError):
        document(**{field: value})


def test_valid_integer_and_string_values_preserve_existing_behavior():
    assert block(index=0, quote_depth=0, text="").text == ""
    assert block(start_line=2, end_line=3, quote_depth=1).quote_depth == 1
    assert ExtractedListItem(1, 2, 1, True, 0).ordinal == 0
    assert ExtractedListItem(1, 2, 1, False).ordinal is None
    assert document(
        source_entity_tag="etag", extractor_id="nexus.txt", extractor_version="1"
    ).blocks == (block(),)


def test_page_provenance_preserves_order_without_source_lines():
    first = ExtractedBlock(0, Kind.PARAGRAPH, "first", page_number=1)
    second = ExtractedBlock(1, Kind.PARAGRAPH, "second", page_number=3)
    assert document(blocks=(first, second)).blocks == (first, second)
    assert first.start_line is None and first.end_line is None


@pytest.mark.parametrize("page", [True, False, 0, -1, 1.0, "1"])
def test_page_number_requires_a_positive_actual_integer(page):
    with pytest.raises(ValueError):
        ExtractedBlock(0, Kind.PARAGRAPH, "content", page_number=page)


@pytest.mark.parametrize(
    "kwargs", [{"start_line": 1}, {"end_line": 2}, {"start_line": 1, "end_line": 2}]
)
def test_page_blocks_cannot_also_have_line_provenance(kwargs):
    with pytest.raises(ValueError):
        ExtractedBlock(0, Kind.PARAGRAPH, "content", page_number=1, **kwargs)


def test_document_rejects_mixed_or_decreasing_page_provenance():
    with pytest.raises(ValueError):
        document(blocks=(block(), ExtractedBlock(1, Kind.TEXT, "page", page_number=1)))
    with pytest.raises(ValueError):
        document(
            blocks=(
                ExtractedBlock(0, Kind.TEXT, "page", page_number=2),
                ExtractedBlock(1, Kind.TEXT, "page", page_number=1),
            )
        )


def test_original_positional_block_arguments_keep_their_meaning():
    item = ExtractedListItem(1, 1, 1, False)
    value = ExtractedBlock(0, Kind.HEADING, "heading", 1, 2, 2, item, 1)
    assert value.start_line == 1 and value.end_line == 2
    assert value.heading_level == 2 and value.list_item is item
    assert value.quote_depth == 1 and value.page_number is None


@pytest.mark.parametrize("count", [True, 0, -1, 1.0, "3", 2])
def test_page_count_rejects_invalid_types_and_excluded_pages(count):
    with pytest.raises(ValueError):
        ExtractedDocument(
            UUID(int=1),
            "etag",
            "nexus.pdf",
            "1",
            (ExtractedBlock(0, Kind.PARAGRAPH, "content", page_number=3),),
            count,
        )


def test_page_count_is_optional_final_field_and_not_valid_for_lines():
    page = ExtractedBlock(0, Kind.PARAGRAPH, "content", page_number=3)
    assert (
        ExtractedDocument(UUID(int=1), "etag", "nexus.pdf", "1", (page,)).page_count
        is None
    )
    assert (
        ExtractedDocument(UUID(int=1), "etag", "nexus.pdf", "1", (page,), 5).page_count
        == 5
    )
    assert document().page_count is None
    with pytest.raises(ValueError):
        document(page_count=1)
