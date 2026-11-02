from __future__ import annotations

import ast
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from uuid import UUID

import pytest

from nexus.documents.domain.extracted_document import (
    ExtractedBlockKind,
    ExtractedListItem,
)
from nexus.documents.domain.segmented_document import (
    DocumentChunkCandidate,
    DocumentChunkKind,
    SourceContribution,
)
from nexus.retrieval.domain import (
    MAX_QUERY_LENGTH,
    MAX_TOP_K,
    RetrievalRequest,
    RetrievalResult,
    RetrievalScope,
    RetrievedChunk,
)


@pytest.fixture
def retrieval_request() -> RetrievalRequest:
    return RetrievalRequest(RetrievalScope(UUID(int=1)), "original query", 3)


@pytest.fixture
def retrieved() -> RetrievedChunk:
    item = ExtractedListItem(8, 9, 2, True, 3)
    contributions = tuple(
        SourceContribution(
            source_block_index=5,
            kind=ExtractedBlockKind.CODE,
            start_line=9,
            end_line=12,
            list_item=item,
            quote_depth=2,
            text_start=start,
            text_end=end,
        )
        for start, end in ((0, 4), (4, 8))
    )
    return RetrievedChunk(
        organization_public_id=UUID(int=1),
        document_public_id=UUID(int=2),
        source_file_public_id=UUID(int=3),
        chunk=DocumentChunkCandidate(
            index=7,
            kind=DocumentChunkKind.LIST,
            text="content!",
            section_path=(0, 2),
            contributions=contributions,
        ),
        source_entity_tag='"source-v1"',
        processing_version="dp-11-v1",
        extractor_id="markdown",
        extractor_version="1",
        normalizer_id="nexus.normalizer",
        normalizer_version="2",
        segmenter_id="nexus.structure",
        segmenter_version="3",
    )


@pytest.mark.parametrize(
    "value", [None, "not-a-uuid", str(UUID(int=1)), 1, UUID(int=0)]
)
def test_scope_rejects_invalid_or_zero_organization(value):
    with pytest.raises(ValueError):
        RetrievalScope(value)


def test_scope_and_request_require_explicit_arguments():
    with pytest.raises(TypeError):
        RetrievalScope()
    with pytest.raises(TypeError):
        RetrievalRequest(RetrievalScope(UUID(int=1)), "query")


@pytest.mark.parametrize(
    "value", [None, UUID(int=1), {"organization_public_id": UUID(int=1)}]
)
def test_request_requires_scope_contract(retrieval_request, value):
    with pytest.raises(TypeError):
        replace(retrieval_request, scope=value)


@pytest.mark.parametrize("value", [None, 1, True, b"query", "", " \t\n", "x" * 8193])
def test_request_rejects_invalid_or_oversized_query(retrieval_request, value):
    with pytest.raises(ValueError):
        replace(retrieval_request, query=value)


@pytest.mark.parametrize("value", ["x", "é" * 8192, " \t日本語 Café: A+B?\n"])
def test_valid_query_is_preserved_exactly(retrieval_request, value):
    assert replace(retrieval_request, query=value).query == value
    assert MAX_QUERY_LENGTH == 8192


@pytest.mark.parametrize("value", [1, 100])
def test_top_k_accepts_both_boundaries(retrieval_request, value):
    assert replace(retrieval_request, top_k=value).top_k == value
    assert MAX_TOP_K == 100


@pytest.mark.parametrize("value", [None, True, False, 1.0, "1", 0, -1, 101])
def test_top_k_requires_an_exact_bounded_integer(retrieval_request, value):
    with pytest.raises(ValueError):
        replace(retrieval_request, top_k=value)


def test_all_contracts_and_nested_source_values_are_immutable(
    retrieval_request, retrieved
):
    result = RetrievalResult(retrieval_request, (retrieved,))
    for value, field in (
        (retrieval_request.scope, "organization_public_id"),
        (retrieval_request, "query"),
        (retrieved, "chunk"),
        (retrieved.chunk, "text"),
        (retrieved.chunk.contributions[0], "text_start"),
        (retrieved.chunk.contributions[0].list_item, "depth"),
        (result, "chunks"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, None)


def test_logical_identity_uses_document_generation_and_original_chunk_index(retrieved):
    assert retrieved.identity == (UUID(int=2), 7)
    assert retrieved.chunk_index == retrieved.chunk.index == 7
    assert replace(retrieved).identity == retrieved.identity
    other_chunk = replace(retrieved, chunk=replace(retrieved.chunk, index=8))
    generation = replace(retrieved, document_public_id=UUID(int=4))
    assert len({retrieved.identity, other_chunk.identity, generation.identity}) == 3
    assert generation.source_file_public_id == retrieved.source_file_public_id


def test_source_identity_versions_and_structured_line_provenance_survive(
    retrieval_request, retrieved
):
    result = RetrievalResult(retrieval_request, (retrieved,))
    value = result.chunks[0]
    assert value is retrieved
    assert value.source_file_public_id == UUID(int=3)
    assert value.source_entity_tag == '"source-v1"'
    assert value.processing_version == "dp-11-v1"
    assert (value.extractor_id, value.extractor_version) == ("markdown", "1")
    assert (value.normalizer_id, value.normalizer_version) == ("nexus.normalizer", "2")
    assert (value.segmenter_id, value.segmenter_version) == ("nexus.structure", "3")
    assert value.chunk.text == "content!"
    assert value.chunk.kind is DocumentChunkKind.LIST
    assert value.chunk.section_path == (0, 2)
    assert value.chunk.source_block_indexes == (5,)
    first, second = value.chunk.contributions
    assert first.kind is ExtractedBlockKind.CODE
    assert (first.start_line, first.end_line, first.quote_depth) == (9, 12, 2)
    assert first.list_item == ExtractedListItem(8, 9, 2, True, 3)
    assert (first.text_start, first.text_end, second.text_start, second.text_end) == (
        0,
        4,
        4,
        8,
    )


def test_noncontiguous_page_provenance_is_preserved(retrieval_request, retrieved):
    contributions = tuple(
        SourceContribution(i, ExtractedBlockKind.TEXT, page_number=page)
        for i, page in enumerate((2, 4, 4))
    )
    candidate = DocumentChunkCandidate(
        7, DocumentChunkKind.TEXT, "page text", (), contributions
    )
    value = replace(retrieved, chunk=candidate, page_count=5)
    result = RetrievalResult(retrieval_request, (value,))
    assert result.chunks[0].chunk.contributions == contributions
    assert result.chunks[0].chunk.page_numbers == (2, 4)
    assert result.chunks[0].page_count == 5
    assert replace(value, page_count=None).chunk is candidate
    for invalid in (True, 0, 3, 5.0, "5"):
        with pytest.raises(ValueError):
            replace(value, page_count=invalid)


@pytest.mark.parametrize(
    "field", ["organization_public_id", "document_public_id", "source_file_public_id"]
)
@pytest.mark.parametrize("value", [None, "invalid", 1, UUID(int=0)])
def test_retrieved_chunk_requires_valid_public_identities(retrieved, field, value):
    with pytest.raises(ValueError):
        replace(retrieved, **{field: value})


@pytest.mark.parametrize("value", [None, {}, "chunk"])
def test_retrieved_chunk_requires_authoritative_candidate(retrieved, value):
    with pytest.raises(TypeError):
        replace(retrieved, chunk=value)


@pytest.mark.parametrize(
    "field",
    [
        "source_entity_tag",
        "extractor_id",
        "extractor_version",
        "normalizer_id",
        "normalizer_version",
        "segmenter_id",
        "segmenter_version",
    ],
)
@pytest.mark.parametrize("value", [None, 1, " \n", "x" * 1025])
def test_retrieved_metadata_requires_bounded_meaningful_strings(
    retrieved, field, value
):
    with pytest.raises(ValueError):
        replace(retrieved, **{field: value})


@pytest.mark.parametrize(
    "value", [None, 1, "", "  ", " version", "version ", "x" * 129]
)
def test_processing_version_matches_document_rules(retrieved, value):
    with pytest.raises(ValueError):
        replace(retrieved, processing_version=value)


def test_metadata_boundaries_do_not_trim_source_values(retrieved):
    value = replace(
        retrieved,
        processing_version="v" * 128,
        source_entity_tag=" " + "x" * 1022 + " ",
    )
    assert value.processing_version == "v" * 128
    assert value.source_entity_tag == " " + "x" * 1022 + " "


def test_line_provenance_cannot_claim_a_total_page_count(retrieved):
    with pytest.raises(ValueError):
        replace(retrieved, page_count=1)


def test_empty_results_and_original_ranking_order(retrieval_request, retrieved):
    assert RetrievalResult(retrieval_request, ()).chunks == ()
    second = replace(retrieved, chunk=replace(retrieved.chunk, index=1))
    generation = replace(retrieved, document_public_id=UUID(int=4))
    values = (retrieved, generation, second)
    assert RetrievalResult(retrieval_request, values).chunks == values


def test_result_accepts_exact_top_k_and_rejects_overflow(retrieval_request, retrieved):
    values = tuple(
        replace(retrieved, chunk=replace(retrieved.chunk, index=i)) for i in range(100)
    )
    assert (
        len(RetrievalResult(replace(retrieval_request, top_k=100), values).chunks)
        == 100
    )
    assert (
        RetrievalResult(replace(retrieval_request, top_k=1), values[:1]).chunks
        == values[:1]
    )
    with pytest.raises(ValueError):
        RetrievalResult(replace(retrieval_request, top_k=1), values[:2])


@pytest.mark.parametrize(
    "value,error",
    [(None, ValueError), ([], ValueError), ([None], ValueError), ((None,), TypeError)],
)
def test_result_requires_immutable_typed_chunks(retrieval_request, value, error):
    with pytest.raises(error):
        RetrievalResult(retrieval_request, value)


@pytest.mark.parametrize("value", [None, {}, RetrievalScope(UUID(int=1))])
def test_result_requires_its_request(value):
    with pytest.raises(TypeError):
        RetrievalResult(value, ())


def test_result_rejects_foreign_tenant_even_with_matching_chunk_identity(
    retrieval_request, retrieved
):
    foreign = replace(retrieved, organization_public_id=UUID(int=99))
    with pytest.raises(ValueError, match="tenant mismatch"):
        RetrievalResult(retrieval_request, (foreign,))


def test_result_rejects_duplicates_even_when_content_differs(
    retrieval_request, retrieved
):
    changed = replace(retrieved, chunk=replace(retrieved.chunk, text="different"))
    for duplicate in (retrieved, replace(retrieved), changed):
        with pytest.raises(ValueError, match="duplicate chunk identities"):
            RetrievalResult(retrieval_request, (retrieved, duplicate))


def test_representations_exclude_query_content_and_source_metadata(
    retrieval_request, retrieved
):
    for value in (
        retrieval_request,
        retrieved,
        RetrievalResult(retrieval_request, (retrieved,)),
    ):
        rendered = repr(value)
        for sensitive in (
            retrieval_request.query,
            retrieved.chunk.text,
            retrieved.source_entity_tag,
        ):
            assert sensitive not in rendered


def test_retrieval_domain_depends_only_on_domain_values_and_standard_library():
    root = (
        Path(__file__).resolve().parents[3] / "src" / "nexus" / "retrieval" / "domain"
    )
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.level == 0, (path, node.module)
                modules = [node.module]
            else:
                continue
            for module in modules:
                if module.startswith(
                    ("nexus.retrieval.domain.", "nexus.documents.domain.")
                ):
                    continue
                assert module.split(".", 1)[0] in sys.stdlib_module_names, (
                    path,
                    module,
                )
