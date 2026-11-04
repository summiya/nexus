"""PostgreSQL RF-05 tests for atomic, tenant-scoped embedding generations."""

import asyncio
from dataclasses import dataclass, replace
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session
from tests.integration.persistence.test_chunk_embedding_migration import seed_tenant

from nexus.infrastructure.persistence import _chunk_embedding_queries as queries
from nexus.infrastructure.persistence.chunk_embedding import (
    SqlAlchemyChunkEmbeddingPersistence,
)
from nexus.infrastructure.persistence.models import (
    ChunkEmbedding,
    ConfiguredModel,
    Document,
    DocumentChunk,
    DocumentChunkSet,
    ModelProvider,
    Organization,
)
from nexus.retrieval.domain.chunk_embeddings import (
    ChunkEmbeddingBatch,
    ChunkEmbeddingVector,
)
from nexus.retrieval.ports.chunk_embedding_persistence import (
    ChunkEmbeddingConflictError,
    ChunkEmbeddingPersistenceError,
    StoredChunkEmbeddingCorruptionError,
)

FIRST_VECTOR = (1.0,) + (0.0,) * 1535
SECOND_VECTOR = (0.0, 1.0) + (0.0,) * 1534


@dataclass(frozen=True)
class Tenant:
    organization_public_id: UUID
    document_public_id: UUID
    configured_model_public_id: UUID
    organization_id: int
    document_id: int
    model_id: int
    provider_id: int
    first_chunk_id: int
    second_chunk_id: int


@dataclass(frozen=True)
class Context:
    engine: object
    sessions: object
    current: Tenant
    other: Tenant

    def persistence(self) -> SqlAlchemyChunkEmbeddingPersistence:
        return SqlAlchemyChunkEmbeddingPersistence(self.sessions)


def seed(engine, *, second_chunk: bool = True) -> Tenant:
    source = seed_tenant(engine)
    with Session(engine) as session:
        organization = session.get(Organization, source.organization_id)
        document = session.get(Document, source.document_id)
        model = session.get(ConfiguredModel, source.model_id)
        chunk = session.get(DocumentChunk, source.chunk_id)
        assert organization and document and model and chunk
        second_id = 0
        if second_chunk:
            extra = DocumentChunk(
                document_id=source.document_id,
                organization_id=source.organization_id,
                chunk_index=1,
                text="Second authoritative chunk",
                kind="text",
                section_path=[],
                contributions=chunk.contributions,
            )
            session.add(extra)
            session.execute(
                update(DocumentChunkSet)
                .where(DocumentChunkSet.document_id == source.document_id)
                .values(chunk_count=2)
            )
            session.flush()
            second_id = extra.id
        result = Tenant(
            organization.public_id,
            document.public_id,
            model.public_id,
            source.organization_id,
            source.document_id,
            source.model_id,
            source.provider_id,
            source.chunk_id,
            second_id,
        )
        session.commit()
        return result


@pytest.fixture
def context(migrated_database, persistence_async_session_factory) -> Context:
    config, engine = migrated_database
    command.upgrade(config, "head")
    return Context(
        engine,
        persistence_async_session_factory,
        seed(engine),
        seed(engine),
    )


def batch(
    tenant: Tenant,
    *,
    indexes: tuple[int, ...] = (0, 1),
    generation: int = 1,
    version: str = "rf-v1",
    vectors: tuple[tuple[float, ...], ...] | None = None,
) -> ChunkEmbeddingBatch:
    if vectors is None:
        vectors = tuple(FIRST_VECTOR if index == 0 else SECOND_VECTOR for index in indexes)
    return ChunkEmbeddingBatch(
        organization_public_id=tenant.organization_public_id,
        document_public_id=tenant.document_public_id,
        configured_model_public_id=tenant.configured_model_public_id,
        embedding_generation=generation,
        embedding_version=version,
        provider_type="openai",
        provider_model_name="text-embedding-3-small",
        embedding_dimension=1536,
        vectors=tuple(
            ChunkEmbeddingVector(chunk_index=index, values=values)
            for index, values in zip(indexes, vectors, strict=True)
        ),
    )


def write(context: Context, value: ChunkEmbeddingBatch) -> None:
    asyncio.run(context.persistence().persist_batch(value))


def read(
    context: Context,
    value: ChunkEmbeddingBatch,
    *,
    indexes: tuple[int, ...] | None = None,
) -> ChunkEmbeddingBatch | None:
    return asyncio.run(
        context.persistence().read_batch(
            organization_public_id=value.organization_public_id,
            document_public_id=value.document_public_id,
            configured_model_public_id=value.configured_model_public_id,
            embedding_generation=value.embedding_generation,
            chunk_indices=value.chunk_indices if indexes is None else indexes,
        )
    )


def row_count(context: Context) -> int:
    with Session(context.engine) as session:
        return session.scalar(select(func.count()).select_from(ChunkEmbedding))


def test_atomic_round_trip_metadata_float32_and_identical_retry(context):
    first = (0.1, 0.2) + (0.0,) * 1534
    value = batch(context.current, vectors=(first, SECOND_VECTOR))
    write(context, value)
    stored = read(context, value)
    assert stored is not None
    assert stored.organization_public_id == value.organization_public_id
    assert stored.document_public_id == value.document_public_id
    assert stored.configured_model_public_id == value.configured_model_public_id
    assert stored.embedding_version == "rf-v1"
    assert stored.embedding_generation == 1
    assert stored.chunk_indices == (0, 1)
    assert stored.vectors[0].values[0] == pytest.approx(0.1)
    assert stored.vectors[0].values[1] == pytest.approx(0.2)

    write(context, value)  # Duplicate float64 values compare exactly as float32.
    assert row_count(context) == 2


def test_multiple_bounded_batches_complete_one_document_generation(context):
    value = batch(context.current)
    write(context, batch(context.current, indexes=(1,)))
    write(context, batch(context.current, indexes=(0,)))
    write(context, value)
    assert row_count(context) == 2
    assert read(context, value).chunk_indices == (0, 1)
    assert read(context, value, indexes=(0,)).chunk_indices == (0,)


def test_identical_chunk_generation_conflicts_on_changed_vector(context):
    value = batch(context.current)
    write(context, value)
    changed = batch(context.current, vectors=(SECOND_VECTOR, SECOND_VECTOR))
    with pytest.raises(ChunkEmbeddingConflictError, match="^Chunk embedding persistence conflict$"):
        write(context, changed)
    assert row_count(context) == 2
    assert read(context, value).vectors[0].values == FIRST_VECTOR


def test_conflicting_partial_batch_does_not_insert_new_vectors(context):
    initial = batch(context.current, indexes=(0,))
    write(context, initial)
    changed = batch(context.current, vectors=(SECOND_VECTOR, SECOND_VECTOR))
    with pytest.raises(ChunkEmbeddingConflictError):
        write(context, changed)
    assert row_count(context) == 1
    assert read(context, changed, indexes=(1,)) is None


def test_changed_version_across_batches_rejected_and_new_generation_allowed(context):
    original = batch(context.current, indexes=(0,))
    write(context, original)
    with pytest.raises(ChunkEmbeddingConflictError):
        write(context, batch(context.current, indexes=(1,), version="rf-v2"))
    assert row_count(context) == 1

    replacement = batch(context.current, indexes=(0,), generation=2, version="rf-v2")
    write(context, replacement)
    assert row_count(context) == 2
    assert read(context, replacement).embedding_version == "rf-v2"
    assert read(context, original).embedding_version == "rf-v1"


def test_wrong_tenant_document_and_model_are_indistinguishable(context):
    value = batch(context.current, indexes=(0,))
    write(context, value)

    for forged in (
        replace(value, organization_public_id=context.other.organization_public_id),
        replace(value, document_public_id=context.other.document_public_id),
        replace(value, document_public_id=uuid4()),
        replace(value, configured_model_public_id=context.other.configured_model_public_id),
    ):
        with pytest.raises(ChunkEmbeddingConflictError, match="^Chunk embedding persistence conflict$"):
            write(context, forged)
        assert read(context, forged) is None
    assert row_count(context) == 1


def test_non_authoritative_chunk_and_incomplete_document_rejected(context):
    with pytest.raises(ChunkEmbeddingConflictError):
        write(context, batch(context.current, indexes=(3,)))
    assert row_count(context) == 0

    with Session(context.engine) as session:
        session.execute(
            update(Document)
            .where(Document.id == context.current.document_id)
            .values(status="processing", processing_completed_at=None)
        )
        session.commit()
    with pytest.raises(ChunkEmbeddingConflictError):
        write(context, batch(context.current, indexes=(0,)))
    assert row_count(context) == 0


def test_disabled_model_and_provider_allow_exact_retry_but_reject_new_row(context):
    value = batch(context.current, indexes=(0,))
    write(context, value)
    with Session(context.engine) as session:
        session.execute(
            update(ModelProvider)
            .where(ModelProvider.id == context.current.provider_id)
            .values(enabled=False)
        )
        session.commit()
    write(context, value)
    with pytest.raises(ChunkEmbeddingConflictError):
        write(context, batch(context.current, indexes=(1,)))
    assert row_count(context) == 1


def test_snapshot_mismatch_with_mutable_model_configuration_rejected(context):
    with Session(context.engine) as session:
        session.execute(
            update(ConfiguredModel)
            .where(ConfiguredModel.id == context.current.model_id)
            .values(provider_model_name="other-embedding-model")
        )
        session.commit()
    with pytest.raises(ChunkEmbeddingConflictError):
        write(context, batch(context.current, indexes=(0,)))
    assert row_count(context) == 0


def test_float32_overflow_and_underflow_fail_before_database_writes(context):
    for vector in (
        (1e100,) + (0.0,) * 1535,
        (1e-100,) + (0.0,) * 1535,
    ):
        with pytest.raises(ChunkEmbeddingPersistenceError, match="^Chunk embedding persistence failed$"):
            write(context, batch(context.current, indexes=(0,), vectors=(vector,)))
    assert row_count(context) == 0


def test_reader_rejects_inconsistent_generation_metadata(context):
    original = batch(context.current, indexes=(0,))
    write(context, original)
    with Session(context.engine) as session:
        session.execute(
            insert(ChunkEmbedding).values(
                organization_id=context.current.organization_id,
                chunk_id=context.current.second_chunk_id,
                configured_model_id=context.current.model_id,
                model_type="embedding",
                provider_type="openai",
                provider_model_name="text-embedding-3-small",
                embedding_dimension=1536,
                embedding_generation=1,
                embedding_version="rf-v2",
                embedding=list(SECOND_VECTOR),
            )
        )
        session.commit()
    with pytest.raises(
        StoredChunkEmbeddingCorruptionError,
        match="^Stored chunk embedding data is invalid$",
    ):
        read(context, batch(context.current))
    with pytest.raises(ChunkEmbeddingConflictError):
        write(context, batch(context.current, indexes=(1,)))
    assert row_count(context) == 2


def test_failed_transaction_rolls_back_without_partial_embeddings(context, monkeypatch):
    original = queries.insert_embeddings

    async def fail_after_insert(session, rows):
        await original(session, rows)
        raise ValueError("sensitive database failure text")

    monkeypatch.setattr(queries, "insert_embeddings", fail_after_insert)
    with pytest.raises(
        ChunkEmbeddingPersistenceError, match="^Chunk embedding persistence failed$"
    ) as error:
        write(context, batch(context.current))
    assert "sensitive" not in str(error.value)
    assert row_count(context) == 0
    monkeypatch.setattr(queries, "insert_embeddings", original)
    write(context, batch(context.current))
    assert row_count(context) == 2


def test_concurrent_writers_serialize_and_duplicate_idempotently(context, monkeypatch):
    original = queries.insert_embeddings
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(session, rows):
        await original(session, rows)
        entered.set()
        await release.wait()

    monkeypatch.setattr(queries, "insert_embeddings", delayed)

    async def scenario():
        persistence = context.persistence()
        value = batch(context.current, indexes=(0,))
        first = asyncio.create_task(persistence.persist_batch(value))
        await entered.wait()
        second = asyncio.create_task(persistence.persist_batch(value))
        await asyncio.sleep(0)
        assert not second.done()
        try:
            assert await persistence.read_batch(
                organization_public_id=value.organization_public_id,
                document_public_id=value.document_public_id,
                configured_model_public_id=value.configured_model_public_id,
                embedding_generation=1,
                chunk_indices=(0,),
            ) is None
        finally:
            release.set()
        assert await asyncio.gather(first, second, return_exceptions=True) == [None, None]

    asyncio.run(asyncio.wait_for(scenario(), 10))
    assert row_count(context) == 1


def test_cancellation_waits_for_transaction_settlement_and_retry_is_safe(
    context, monkeypatch
):
    original = queries.insert_embeddings
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(session, rows):
        await original(session, rows)
        entered.set()
        await release.wait()

    monkeypatch.setattr(queries, "insert_embeddings", delayed)

    async def scenario():
        persistence = context.persistence()
        value = batch(context.current, indexes=(0,))
        task = asyncio.create_task(persistence.persist_batch(value))
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await persistence.read_batch(
            organization_public_id=value.organization_public_id,
            document_public_id=value.document_public_id,
            configured_model_public_id=value.configured_model_public_id,
            embedding_generation=1,
            chunk_indices=(0,),
        ) is not None
        await persistence.persist_batch(value)

    asyncio.run(asyncio.wait_for(scenario(), 10))
    assert row_count(context) == 1


def test_reader_is_bounded_and_validates_public_identity(context):
    value = batch(context.current, indexes=(0,))
    write(context, value)
    for indices in ((), (-1,), (0, 0)):
        with pytest.raises(ValueError):
            read(context, value, indexes=indices)
    with pytest.raises(ValueError):
        asyncio.run(
            context.persistence().read_batch(
                organization_public_id=UUID(int=0),
                document_public_id=value.document_public_id,
                configured_model_public_id=value.configured_model_public_id,
                embedding_generation=1,
                chunk_indices=(0,),
            )
        )
    assert row_count(context) == 1
