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
