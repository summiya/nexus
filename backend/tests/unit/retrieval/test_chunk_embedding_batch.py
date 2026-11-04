"""Pure RF-05 validation; malformed embeddings cannot reach persistence."""

from dataclasses import replace
from math import inf, nan
from uuid import UUID, uuid4

import pytest

from nexus.retrieval.domain.chunk_embeddings import (
    MAX_EMBEDDINGS_PER_BATCH,
    ChunkEmbeddingBatch,
    ChunkEmbeddingVector,
    require_chunk_indices,
)

BASE_VECTOR = (1.0,) + (0.0,) * 1535


def example_batch() -> ChunkEmbeddingBatch:
    return ChunkEmbeddingBatch(
        organization_public_id=uuid4(),
        document_public_id=uuid4(),
        configured_model_public_id=uuid4(),
        embedding_generation=1,
        embedding_version="rf-v1",
        provider_type="openai",
        provider_model_name="text-embedding-3-small",
        embedding_dimension=1536,
        vectors=(ChunkEmbeddingVector(chunk_index=0, values=BASE_VECTOR),),
    )


def test_valid_batch_is_immutable_and_keeps_vector_payload_out_of_repr():
    batch = example_batch()
    assert batch.chunk_indices == (0,)
    assert batch.vectors[0].values == BASE_VECTOR
    assert "1.0" not in repr(batch)
    assert "1.0" not in repr(batch.vectors[0])
    with pytest.raises(AttributeError):
        batch.embedding_generation = 2  # type: ignore[misc]


@pytest.mark.parametrize(
    "vector",
    [
        (),
        BASE_VECTOR[:-1],
        (0.0,) * 1536,
        (nan,) + BASE_VECTOR[1:],
        (inf,) + BASE_VECTOR[1:],
        (True,) + BASE_VECTOR[1:],
        (1,) + BASE_VECTOR[1:],
    ],
)
def test_invalid_vectors_are_rejected(vector):
    with pytest.raises(ValueError):
        ChunkEmbeddingVector(chunk_index=0, values=vector)


@pytest.mark.parametrize("index", [-1, True, 1.5])
def test_invalid_chunk_indices_are_rejected(index):
    with pytest.raises(ValueError):
        ChunkEmbeddingVector(chunk_index=index, values=BASE_VECTOR)


@pytest.mark.parametrize(
    "attribute,value",
    [
        ("organization_public_id", UUID(int=0)),
        ("document_public_id", UUID(int=0)),
        ("configured_model_public_id", UUID(int=0)),
        ("embedding_generation", 0),
        ("embedding_generation", True),
        ("embedding_version", ""),
        ("embedding_version", " blank"),
        ("embedding_version", "blank "),
        ("embedding_version", "x" * 129),
        ("provider_type", "anthropic"),
        ("provider_model_name", "text-embedding-3-large"),
        ("embedding_dimension", 768),
    ],
)
def test_invalid_generation_metadata_is_rejected(attribute, value):
    with pytest.raises(ValueError):
        replace(example_batch(), **{attribute: value})


@pytest.mark.parametrize("indexes", [(), (1, 1), (2, 1), (-1,), (1, True), (0,) * 129])
def test_invalid_index_sequences_rejected(indexes):
    with pytest.raises(ValueError):
        require_chunk_indices(indexes)


def test_batches_are_bounded_but_support_partial_document_generations():
    sample = example_batch()
    vectors = tuple(
        ChunkEmbeddingVector(chunk_index=index, values=BASE_VECTOR)
        for index in range(MAX_EMBEDDINGS_PER_BATCH)
    )
    assert len(replace(sample, vectors=vectors).vectors) == MAX_EMBEDDINGS_PER_BATCH
    with pytest.raises(ValueError):
        replace(
            sample,
            vectors=vectors
            + (ChunkEmbeddingVector(chunk_index=128, values=BASE_VECTOR),),
        )


def test_duplicate_or_unsorted_batch_index_is_rejected():
    sample = example_batch()
    for indexes in ((0, 0), (1, 0)):
        with pytest.raises(ValueError):
            replace(
                sample,
                vectors=tuple(
                    ChunkEmbeddingVector(chunk_index=index, values=BASE_VECTOR)
                    for index in indexes
                ),
            )
