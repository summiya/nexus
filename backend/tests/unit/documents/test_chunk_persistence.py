import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.unit.documents.test_segment_document import document

from nexus.documents.application.segment_document import SegmentDocument
from nexus.documents.domain.extracted_document import ExtractedBlockKind as Kind
from nexus.documents.domain.extracted_document import ExtractedListItem
from nexus.documents.domain.segmented_document import SourceContribution
from nexus.documents.ports.chunk_persistence import (
    ChunkConflictError,
    ChunkPersistenceError,
)
from nexus.infrastructure.persistence import _document_chunk_queries as queries
from nexus.infrastructure.persistence.document_chunk import (
    SqlAlchemyDocumentChunkPersistence,
)
from nexus.infrastructure.persistence.models.document_chunk import (
    DocumentChunk,
    DocumentChunkSet,
)


@pytest.mark.parametrize(
    "field",
    [
        "max_chunks",
        "max_text_bytes",
        "max_contributions_per_chunk",
        "max_total_contributions",
        "max_provenance_bytes",
        "batch_size",
    ],
)
@pytest.mark.parametrize("value", [0, -1, True, False, None, 1.5, "2"])
def test_limits_reject_invalid_types_and_values(field, value):
    with pytest.raises(ValueError, match="^Invalid chunk persistence limits$"):
        SqlAlchemyDocumentChunkPersistence(async_sessionmaker(), **{field: value})


def test_explicit_codec_preserves_every_field_without_dataclass_serialization():
    value = SourceContribution(
        5,
        Kind.PARAGRAPH,
        9,
        12,
        list_item=ExtractedListItem(8, 9, 2, True, 3),
        quote_depth=2,
        text_start=0,
        text_end=7,
    )
    payload = queries.encode_contribution(value)
    assert payload == {
        "source_block_index": 5,
        "kind": "paragraph",
        "start_line": 9,
        "end_line": 12,
        "page_number": None,
        "list_item": {
            "list_start_line": 8,
            "item_start_line": 9,
            "depth": 2,
            "ordered": True,
            "ordinal": 3,
        },
        "quote_depth": 2,
        "text_start": 0,
        "text_end": 7,
    }
    assert queries.decode_contribution(payload) == value
    page = SourceContribution(0, Kind.TEXT, page_number=4)
    assert queries.decode_contribution(queries.encode_contribution(page)) == page


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_block_index", True),
        ("kind", "wrong"),
        ("text_start", True),
        ("page_number", True),
        ("list_item", {"depth": 1}),
        ("quote_depth", "2"),
    ],
)
def test_codec_rejects_invalid_types(field, value):
    payload = queries.encode_contribution(SourceContribution(0, Kind.TEXT, 1, 2))
    payload[field] = value
    with pytest.raises((ValueError, TypeError)):
        queries.decode_contribution(payload)


@pytest.mark.parametrize("payload", [None, [], {}, {"unknown": 1}])
def test_codec_rejects_unknown_or_missing_fields(payload):
    with pytest.raises(ValueError):
        queries.decode_contribution(payload)


def test_defaults_cover_standard_envelope_and_errors_are_fixed():
    adapter = SqlAlchemyDocumentChunkPersistence(async_sessionmaker())
    assert (
        adapter._max_chunks,
        adapter._max_text,
        adapter._max_per_chunk,
        adapter._max_total,
        adapter._max_provenance,
        adapter._batch_size,
    ) == (10_000, 16 * 1024 * 1024, 128, 60_000, 16 * 1024 * 1024, 200)
    result = SegmentDocument().execute(
        document((Kind.PARAGRAPH, "é"), (Kind.PARAGRAPH, "second"))
    )
    assert adapter._preflight(result)[0] == queries.chunk_values(result.chunks[0])
    assert str(ChunkPersistenceError()) == "Document chunk persistence failed"
    assert str(ChunkConflictError()) == "Document chunk persistence conflict"
    assert isinstance(ChunkConflictError(), ChunkPersistenceError)


def test_text_utf8_and_provenance_bounds_are_exact():
    import json

    result = SegmentDocument().execute(document((Kind.TEXT, "é")))
    encoded = queries.chunk_values(result.chunks[0])["contributions"]
    size = len(json.dumps(encoded, ensure_ascii=False).encode("utf-8"))
    SqlAlchemyDocumentChunkPersistence(
        async_sessionmaker(), max_text_bytes=2, max_provenance_bytes=size
    )._preflight(result)
    for kwargs in ({"max_text_bytes": 1}, {"max_provenance_bytes": size - 1}):
        with pytest.raises(ChunkPersistenceError):
            SqlAlchemyDocumentChunkPersistence(
                async_sessionmaker(), **kwargs
            )._preflight(result)


def test_small_bounds_check_before_encoding_provenance(monkeypatch):
    result = SegmentDocument().execute(document((Kind.TEXT, "a"), (Kind.TEXT, "b")))

    def unexpected(*args):
        pytest.fail("Contribution bound must be checked before encoding")

    monkeypatch.setattr(queries, "chunk_values", unexpected)
    with pytest.raises(ChunkPersistenceError):
        SqlAlchemyDocumentChunkPersistence(
            async_sessionmaker(), max_contributions_per_chunk=1
        )._preflight(result)


def test_orm_models_have_no_search_fields_or_extra_indexes():
    assert set(DocumentChunk.__table__.columns.keys()) == {
        "id",
        "document_id",
        "organization_id",
        "chunk_index",
        "text",
        "kind",
        "section_path",
        "contributions",
    }
    for model in (DocumentChunk, DocumentChunkSet):
        assert not model.__table__.indexes
        assert any(
            isinstance(c, ForeignKeyConstraint) for c in model.__table__.constraints
        )
        assert any(isinstance(c, UniqueConstraint) for c in model.__table__.constraints)
        assert any(isinstance(c, CheckConstraint) for c in model.__table__.constraints)
