"""RF-06 uses disposable PostgreSQL databases, never the live application database."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.operations import Operations
from sqlalchemy import (
    Engine,
    delete,
    func,
    insert,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session
from tests.integration.helpers import seed_file

from nexus.infrastructure.persistence import (
    _chunk_embedding_queries as embedding_queries,
)
from nexus.infrastructure.persistence import indexing as indexing_module
from nexus.infrastructure.persistence.base import Base
from nexus.infrastructure.persistence.chunk_embedding import (
    SqlAlchemyChunkEmbeddingPersistence,
)
from nexus.infrastructure.persistence.indexing import SqlAlchemyIndexingPersistence
from nexus.infrastructure.persistence.model_provider import (
    SqlAlchemyModelProviderPersistence,
)
from nexus.infrastructure.persistence.models import (
    ChunkEmbedding,
    ConfiguredModel,
    Document,
    DocumentChunk,
    DocumentChunkSet,
    File,
    ModelProvider,
)
from nexus.infrastructure.persistence.models.indexing_generation import (
    IndexingGeneration as GenerationRow,
)
from nexus.model_providers.domain import ConfiguredModelId
from nexus.model_providers.ports import ModelProviderDeleteRestrictedError
from nexus.retrieval.domain.chunk_embeddings import (
    ChunkEmbeddingBatch,
    ChunkEmbeddingVector,
)
from nexus.retrieval.domain.indexing import IndexingGeneration, IndexingStatus
from nexus.retrieval.ports.chunk_embedding_persistence import (
    ChunkEmbeddingConflictError,
)
from nexus.retrieval.ports.indexing_persistence import (
    IndexingConflictError,
    IndexingPersistenceError,
)

PREVIOUS = "20261103_0020"
NOW = datetime(2026, 11, 4, tzinfo=UTC)
CREATED = NOW + timedelta(seconds=1)
START = CREATED + timedelta(seconds=1)
FINISH = START + timedelta(seconds=1)
VECTOR = (1.0,) + (0.0,) * 1535


@dataclass(frozen=True)
class Tenant:
    generation: IndexingGeneration
    organization_id: int
    document_id: int
    model_id: int
    provider_id: int
    chunk_ids: tuple[int, ...]


@dataclass(frozen=True)
class Context:
    config: Config
    engine: Engine
    sessions: async_sessionmaker[AsyncSession]
    tenant: Tenant
    other: Tenant

    def persistence(self) -> SqlAlchemyIndexingPersistence:
        return SqlAlchemyIndexingPersistence(self.sessions)

    def vectors(self) -> SqlAlchemyChunkEmbeddingPersistence:
        return SqlAlchemyChunkEmbeddingPersistence(self.sessions)


def seed(engine: Engine) -> Tenant:
    source = seed_file(engine, status="available")
    with Session(engine) as session:
        file = session.scalar(select(File).where(File.public_id == source.public_id))
        assert file is not None
        document = Document(
            public_id=uuid4(),
            organization_id=file.organization_id,
            source_file_id=file.id,
            status="completed",
            processing_version="dp-v1",
            extractor_version="1",
            created_at=NOW,
            processing_started_at=NOW,
            processing_completed_at=NOW,
        )
        provider = ModelProvider(
            public_id=uuid4(),
            organization_id=file.organization_id,
            provider_type="openai",
            display_name="OpenAI",
            settings_json={},
        )
        session.add_all([document, provider])
        session.flush()
        session.add(
            DocumentChunkSet(
                document_id=document.id,
                organization_id=file.organization_id,
                source_entity_tag="source-etag",
                extractor_id="extractor",
                extractor_version="1",
                normalizer_id="normalizer",
                normalizer_version="1",
                segmenter_id="segmenter",
                segmenter_version="1",
                preferred_chunk_bytes=1024,
                max_chunk_bytes=4096,
                max_source_contributions=128,
                chunk_count=2,
            )
        )
        model = ConfiguredModel(
            public_id=uuid4(),
            organization_id=file.organization_id,
            provider_id=provider.id,
            provider_model_name="text-embedding-3-small",
            display_name="Embedding",
            model_type="embedding",
            capabilities=[],
            embedding_dimension=1536,
        )
        session.add(model)
        session.flush()
        chunks = [
            DocumentChunk(
                document_id=document.id,
                organization_id=file.organization_id,
                chunk_index=index,
                text=f"Synthetic authoritative chunk {index}",
                kind="text",
                section_path=[],
                contributions=[
                    {
                        "source_block_index": index,
                        "kind": "text",
                        "start_line": index + 1,
                        "end_line": index + 2,
                        "page_number": None,
                        "list_item": None,
                        "quote_depth": 0,
                        "text_start": None,
                        "text_end": None,
                    }
                ],
            )
            for index in range(2)
        ]
        session.add_all(chunks)
        session.flush()
        generation = IndexingGeneration(
            organization_public_id=source.organization_public_id,
            document_public_id=document.public_id,
            configured_model_public_id=model.public_id,
            embedding_generation=1,
            embedding_version="input-v1",
            provider_type="openai",
            provider_model_name="text-embedding-3-small",
            embedding_dimension=1536,
            created_at=CREATED,
        )
        tenant = Tenant(
            generation,
            file.organization_id,
            document.id,
            model.id,
            provider.id,
            tuple(chunk.id for chunk in chunks),
        )
        session.commit()
        return tenant


@pytest.fixture
def context(migrated_database, persistence_async_session_factory) -> Context:
    config, engine = migrated_database
    command.upgrade(config, "head")
    return Context(
        config, engine, persistence_async_session_factory, seed(engine), seed(engine)
    )


def batch(
    generation: IndexingGeneration, indexes: tuple[int, ...] = (0, 1)
) -> ChunkEmbeddingBatch:
    return ChunkEmbeddingBatch(
        organization_public_id=generation.organization_public_id,
        document_public_id=generation.document_public_id,
        configured_model_public_id=generation.configured_model_public_id,
        embedding_generation=generation.embedding_generation,
        embedding_version=generation.embedding_version,
        provider_type=generation.provider_type,
        provider_model_name=generation.provider_model_name,
        embedding_dimension=generation.embedding_dimension,
        vectors=tuple(ChunkEmbeddingVector(index, VECTOR) for index in indexes),
    )


def create(
    context: Context, generation: IndexingGeneration | None = None
) -> IndexingGeneration:
    return asyncio.run(
        context.persistence().create_generation(generation or context.tenant.generation)
    )


def change(
    context: Context, before: IndexingGeneration, after: IndexingGeneration
) -> None:
    asyncio.run(
        context.persistence().update_generation(expected=before, generation=after)
    )


def read(context: Context, generation: IndexingGeneration) -> IndexingGeneration | None:
    return asyncio.run(
        context.persistence().get_generation(
            organization_public_id=generation.organization_public_id,
            document_public_id=generation.document_public_id,
            configured_model_public_id=generation.configured_model_public_id,
            embedding_generation=generation.embedding_generation,
        )
    )


def write(
    context: Context, generation: IndexingGeneration, indexes: tuple[int, ...] = (0, 1)
) -> None:
    asyncio.run(context.vectors().persist_batch(batch(generation, indexes)))


def processing(context: Context) -> IndexingGeneration:
    initial = create(context)
    current = initial.start(at=START)
    change(context, initial, current)
    return current


def row_values(tenant: Tenant, **changes: object) -> dict[str, object]:
    generation = tenant.generation
    return {
        "organization_id": tenant.organization_id,
        "document_id": tenant.document_id,
        "configured_model_id": tenant.model_id,
        "embedding_generation": generation.embedding_generation,
        "model_type": "embedding",
        "provider_type": generation.provider_type,
        "provider_model_name": generation.provider_model_name,
        "embedding_dimension": generation.embedding_dimension,
        "embedding_version": generation.embedding_version,
        "created_at": generation.created_at,
        "status": "pending",
        "started_at": None,
        "finished_at": None,
        "failure_code": None,
    } | changes


def test_round_trip_creation_replay_and_exact_transition_retry(context):
    initial = create(context)
    assert read(context, initial) == initial
    current = initial.start(at=START)
    change(context, initial, current)
    change(context, initial, current)
    assert create(context, initial) == current
    write(context, current, (1,))
    write(context, current, (0,))
    completed = current.complete(at=FINISH)
    change(context, current, completed)
    change(context, current, completed)
    assert read(context, initial) == completed
    write(context, completed)  # Exact durable vector retries remain safe.
    with Session(context.engine) as session:
        assert session.scalar(select(func.count()).select_from(ChunkEmbedding)) == 2
        assert session.get(Document, context.tenant.document_id).status == "completed"


@pytest.mark.parametrize(
    "kind",
    [
        "foreign-organization",
        "foreign-document",
        "foreign-model",
        "missing-document",
        "missing-model",
    ],
)
def test_tenant_isolation_and_missing_references_are_indistinguishable(context, kind):
    initial = create(context)
    changes = {
        "foreign-organization": {
            "organization_public_id": context.other.generation.organization_public_id
        },
        "foreign-document": {
            "document_public_id": context.other.generation.document_public_id
        },
        "foreign-model": {
            "configured_model_public_id": context.other.generation.configured_model_public_id
        },
        "missing-document": {"document_public_id": uuid4()},
        "missing-model": {"configured_model_public_id": uuid4()},
    }[kind]
    invalid = replace(initial, **changes)
    assert read(context, invalid) is None
    for operation in (
        lambda: create(context, invalid),
        lambda: change(context, invalid, invalid.start(at=START)),
    ):
        with pytest.raises(
            IndexingConflictError, match="^Indexing generation conflict$"
        ):
            operation()
    assert read(context, initial) == initial
    assert read(context, context.other.generation) is None


@pytest.mark.parametrize(
    "kind",
    [
        "processing-document",
        "missing-set",
        "missing-chunk",
        "ghost-index",
        "wrong-count",
        "disabled-model",
        "disabled-provider",
        "chat-model",
        "snapshot-mismatch",
        "unsupported-dimension",
        "before-document-completed",
    ],
)
def test_creation_requires_authoritative_completed_source_and_eligible_v1_model(
    context, kind
):
    tenant = context.tenant
    generation = tenant.generation
    with context.engine.begin() as connection:
        if kind == "processing-document":
            connection.execute(
                update(Document)
                .where(Document.id == tenant.document_id)
                .values(status="processing", processing_completed_at=None)
            )
        elif kind == "missing-set":
            connection.execute(
                delete(DocumentChunk).where(
                    DocumentChunk.document_id == tenant.document_id
                )
            )
            connection.execute(
                delete(DocumentChunkSet).where(
                    DocumentChunkSet.document_id == tenant.document_id
                )
            )
        elif kind == "missing-chunk":
            connection.execute(
                delete(DocumentChunk).where(DocumentChunk.id == tenant.chunk_ids[1])
            )
        elif kind == "ghost-index":
            connection.execute(
                update(DocumentChunk)
                .where(DocumentChunk.id == tenant.chunk_ids[1])
                .values(chunk_index=2)
            )
        elif kind == "wrong-count":
            connection.execute(
                update(DocumentChunkSet)
                .where(DocumentChunkSet.document_id == tenant.document_id)
                .values(chunk_count=1)
            )
        elif kind == "disabled-model":
            connection.execute(
                update(ConfiguredModel)
                .where(ConfiguredModel.id == tenant.model_id)
                .values(enabled=False)
            )
        elif kind == "disabled-provider":
            connection.execute(
                update(ModelProvider)
                .where(ModelProvider.id == tenant.provider_id)
                .values(enabled=False)
            )
        elif kind == "chat-model":
            connection.execute(
                update(ConfiguredModel)
                .where(ConfiguredModel.id == tenant.model_id)
                .values(model_type="chat", embedding_dimension=None)
            )
        elif kind == "snapshot-mismatch":
            generation = replace(generation, provider_model_name="another-model")
        elif kind == "unsupported-dimension":
            connection.execute(
                update(ConfiguredModel)
                .where(ConfiguredModel.id == tenant.model_id)
                .values(embedding_dimension=768)
            )
            generation = replace(generation, embedding_dimension=768)
        else:
            generation = replace(generation, created_at=NOW - timedelta(seconds=1))
    with pytest.raises(IndexingConflictError):
        create(context, generation)
    assert read(context, generation) is None


def test_legacy_cutover_and_generation_collision_rules(context):
    legacy = replace(context.tenant.generation, embedding_generation=5)
    write(context, legacy, (0,))
    for number in (1, 5, 7):
        with pytest.raises(IndexingConflictError):
            create(context, replace(legacy, embedding_generation=number))
    tracked = create(context, replace(legacy, embedding_generation=6))
    assert read(context, legacy) is None
    write(context, legacy)  # Existing untracked generations may finish their batches.
    with pytest.raises(ChunkEmbeddingConflictError):
        write(context, replace(legacy, embedding_generation=7))
    with pytest.raises(IndexingConflictError):
        create(
            context, replace(tracked, embedding_generation=7)
        )  # One active generation.
    failed = tracked.fail(at=FINISH, code="ABANDONED")
    change(context, tracked, failed)
    next_generation = replace(
        legacy, embedding_generation=7, embedding_version="input-v2"
    )
    assert create(context, next_generation) == next_generation
    with Session(context.engine) as session:
        assert session.scalar(select(func.count()).select_from(ChunkEmbedding)) == 2


def test_pending_and_failed_generations_fence_new_vectors_but_allow_exact_replays(
    context,
):
    initial = create(context)
    with pytest.raises(ChunkEmbeddingConflictError):
        write(context, initial, (0,))
    active = initial.start(at=START)
    change(context, initial, active)
    write(context, active, (0,))
    with pytest.raises(ChunkEmbeddingConflictError):
        write(context, replace(active, embedding_version="another-version"), (1,))
    failed = active.fail(at=FINISH, code="FAILED")
    change(context, active, failed)
    write(context, failed, (0,))
    with pytest.raises(ChunkEmbeddingConflictError):
        write(context, failed, (1,))
    assert read(context, initial) == failed


def test_failed_precondition_and_disabled_model_preserve_historical_state(context):
    initial = create(context)
    with context.engine.begin() as connection:
        connection.execute(
            update(ConfiguredModel)
            .where(ConfiguredModel.id == context.tenant.model_id)
            .values(enabled=False)
        )
    assert create(context, initial) == initial
    with pytest.raises(IndexingConflictError):
        change(context, initial, initial.start(at=START))
    failed = initial.fail(at=FINISH, code="MODEL_UNAVAILABLE")
    change(context, initial, failed)
    change(context, initial, failed)
    assert read(context, initial) == failed


@pytest.mark.parametrize(
    "kind",
    [
        "empty",
        "partial",
        "other-tenant",
        "other-generation",
        "mixed-version",
        "wrong-dimension",
        "wrong-count",
        "extra-chunk",
    ],
)
def test_completion_requires_exact_authoritative_coverage_and_matching_snapshots(
    context, kind
):
    active = processing(context)
    if kind == "partial":
        write(context, active, (0,))
    elif kind == "other-tenant":
        write(context, context.other.generation)
    elif kind == "other-generation":
        # Existing RF-04 rows remain untracked, even with the same vector count.
        with context.engine.begin() as connection:
            connection.execute(
                insert(ChunkEmbedding),
                [
                    {
                        "organization_id": context.tenant.organization_id,
                        "chunk_id": chunk_id,
                        "configured_model_id": context.tenant.model_id,
                        "model_type": "embedding",
                        "provider_type": active.provider_type,
                        "provider_model_name": active.provider_model_name,
                        "embedding_dimension": 1536,
                        "embedding_generation": 99,
                        "embedding_version": active.embedding_version,
                        "embedding": list(VECTOR),
                    }
                    for chunk_id in context.tenant.chunk_ids
                ],
            )
    elif kind in ("mixed-version", "wrong-dimension", "wrong-count", "extra-chunk"):
        write(context, active)
        with context.engine.begin() as connection:
            if kind == "mixed-version":
                connection.execute(
                    update(ChunkEmbedding)
                    .where(ChunkEmbedding.chunk_id == context.tenant.chunk_ids[1])
                    .values(embedding_version="other-input")
                )
            elif kind == "wrong-dimension":
                # Simulate a corrupt header; RF-04 prevents malformed vector dimensions.
                connection.execute(
                    update(GenerationRow).values(embedding_dimension=768)
                )
                active = replace(active, embedding_dimension=768)
            elif kind == "wrong-count":
                connection.execute(
                    update(DocumentChunkSet)
                    .where(DocumentChunkSet.document_id == context.tenant.document_id)
                    .values(chunk_count=1)
                )
            else:
                connection.execute(
                    insert(DocumentChunk).values(
                        document_id=context.tenant.document_id,
                        organization_id=context.tenant.organization_id,
                        chunk_index=2,
                        text="Ghost chunk",
                        kind="text",
                        section_path=[],
                        contributions=[{"source_block_index": 2}],
                    )
                )
    with pytest.raises(IndexingConflictError):
        change(context, active, active.complete(at=FINISH))
    assert read(context, active).status is IndexingStatus.PROCESSING


def test_snapshot_cas_rejects_forged_identity_metadata_stale_and_terminal_updates(
    context,
):
    initial = create(context)
    active = initial.start(at=START)
    for invalid in (
        replace(active, embedding_version="v2"),
        replace(active, document_public_id=uuid4()),
    ):
        with pytest.raises(IndexingConflictError):
            change(context, initial, invalid)
    change(context, initial, active)
    with pytest.raises(IndexingConflictError):
        change(context, initial, initial.fail(at=FINISH, code="STALE"))
    with pytest.raises(IndexingConflictError):
        create(context, replace(initial, created_at=START))
    failed = active.fail(at=FINISH, code="FAILED")
    change(context, active, failed)
    with pytest.raises(IndexingConflictError):
        change(context, failed, active)
    assert read(context, initial) == failed


def test_concurrent_creations_and_terminal_transitions_serialize(context):
    async def scenario():
        persistence = context.persistence()
        initial = context.tenant.generation
        assert await asyncio.gather(
            persistence.create_generation(initial),
            persistence.create_generation(initial),
        ) == [initial, initial]
        active = initial.start(at=START)
        await persistence.update_generation(expected=initial, generation=active)
        await context.vectors().persist_batch(batch(active))
        outcomes = await asyncio.gather(
            persistence.update_generation(
                expected=active, generation=active.complete(at=FINISH)
            ),
            persistence.update_generation(
                expected=active, generation=active.fail(at=FINISH, code="FAILED")
            ),
            return_exceptions=True,
        )
        assert sum(result is None for result in outcomes) == 1
        assert (
            sum(isinstance(result, IndexingConflictError) for result in outcomes) == 1
        )

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_reservation_waits_for_legacy_writer_and_uses_committed_high_water_mark(
    context, monkeypatch
):
    legacy = replace(context.tenant.generation, embedding_generation=5)
    next_generation = replace(legacy, embedding_generation=6)
    original = embedding_queries.insert_embeddings

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed(session, rows):
            await original(session, rows)
            entered.set()
            await release.wait()

        monkeypatch.setattr(embedding_queries, "insert_embeddings", delayed)
        writer = asyncio.create_task(
            context.vectors().persist_batch(batch(legacy, (0,)))
        )
        await entered.wait()
        try:
            reservation = asyncio.create_task(
                context.persistence().create_generation(next_generation)
            )
            await asyncio.sleep(0)
            assert not reservation.done()
        finally:
            release.set()
        assert await asyncio.gather(writer, reservation) == [None, next_generation]

    asyncio.run(asyncio.wait_for(scenario(), 10))
    assert read(context, legacy) is None
    assert read(context, next_generation) == next_generation


def test_reservation_wins_race_and_prevents_legacy_number_collision(
    context, monkeypatch
):
    initial = context.tenant.generation
    original = indexing_module._eligible_model

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed(session, organization_id, generation):
            model_id = await original(session, organization_id, generation)
            entered.set()
            await release.wait()
            return model_id

        monkeypatch.setattr(indexing_module, "_eligible_model", delayed)
        reservation = asyncio.create_task(
            context.persistence().create_generation(initial)
        )
        await entered.wait()
        try:
            writer = asyncio.create_task(
                context.vectors().persist_batch(batch(initial))
            )
            await asyncio.sleep(0)
            assert not writer.done()
        finally:
            release.set()
        outcomes = await asyncio.gather(reservation, writer, return_exceptions=True)
        assert outcomes[0] == initial
        assert isinstance(outcomes[1], ChunkEmbeddingConflictError)

    asyncio.run(asyncio.wait_for(scenario(), 10))
    with context.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ChunkEmbedding)) == 0


def test_completion_waits_for_inflight_batch_under_document_lock(context, monkeypatch):
    active = processing(context)
    original = embedding_queries.insert_embeddings

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed(session, rows):
            await original(session, rows)
            entered.set()
            await release.wait()

        monkeypatch.setattr(embedding_queries, "insert_embeddings", delayed)
        writer = asyncio.create_task(context.vectors().persist_batch(batch(active)))
        await entered.wait()
        try:
            completion = asyncio.create_task(
                context.persistence().update_generation(
                    expected=active, generation=active.complete(at=FINISH)
                )
            )
            await asyncio.sleep(0)
            assert not completion.done()
        finally:
            release.set()
        assert await asyncio.gather(writer, completion) == [None, None]

    asyncio.run(asyncio.wait_for(scenario(), 10))
    assert read(context, active).status is IndexingStatus.COMPLETED


def test_terminal_transition_fences_an_inflight_waiting_writer(context, monkeypatch):
    active = processing(context)
    original = SqlAlchemyIndexingPersistence._update

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed(self, session, expected, generation):
            await original(self, session, expected, generation)
            entered.set()
            await release.wait()

        monkeypatch.setattr(SqlAlchemyIndexingPersistence, "_update", delayed)
        failure = asyncio.create_task(
            context.persistence().update_generation(
                expected=active, generation=active.fail(at=FINISH, code="FAILED")
            )
        )
        await entered.wait()
        try:
            writer = asyncio.create_task(context.vectors().persist_batch(batch(active)))
            await asyncio.sleep(0)
            assert not writer.done()
        finally:
            release.set()
        outcomes = await asyncio.gather(failure, writer, return_exceptions=True)
        assert outcomes[0] is None
        assert isinstance(outcomes[1], ChunkEmbeddingConflictError)

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_cancellation_waits_for_transaction_settlement_and_creation_retry(
    context, monkeypatch
):
    original = indexing_module._eligible_model

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed(session, organization_id, generation):
            value = await original(session, organization_id, generation)
            entered.set()
            await release.wait()
            return value

        monkeypatch.setattr(indexing_module, "_eligible_model", delayed)
        task = asyncio.create_task(
            context.persistence().create_generation(context.tenant.generation)
        )
        await entered.wait()
        try:
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(asyncio.wait_for(scenario(), 10))
    assert read(context, context.tenant.generation) == context.tenant.generation
    assert create(context) == context.tenant.generation


def test_unexpected_database_failure_rolls_back_creation_and_maps_safely(
    context, monkeypatch
):
    original = AsyncSession.flush

    async def broken(session, *args, **kwargs):
        await original(session, *args, **kwargs)
        raise SQLAlchemyError("private database diagnostics")

    monkeypatch.setattr(AsyncSession, "flush", broken)
    with pytest.raises(IndexingPersistenceError, match="^Indexing persistence failed$"):
        create(context)
    assert read(context, context.tenant.generation) is None


def test_database_rejects_foreign_tenant_and_wrong_model_type_relationships(context):
    tenant = context.tenant
    with context.engine.begin() as connection:
        chat_id = connection.scalar(
            insert(ConfiguredModel)
            .values(
                public_id=uuid4(),
                organization_id=tenant.organization_id,
                provider_id=tenant.provider_id,
                provider_model_name="chat",
                display_name="Chat",
                model_type="chat",
                capabilities=[],
            )
            .returning(ConfiguredModel.id)
        )
    for changes in (
        {"organization_id": context.other.organization_id},
        {"document_id": context.other.document_id},
        {"configured_model_id": context.other.model_id},
        {"configured_model_id": chat_id},
        {"configured_model_id": chat_id, "model_type": "chat"},
    ):
        with pytest.raises(IntegrityError), context.engine.begin() as connection:
            connection.execute(
                insert(GenerationRow).values(**row_values(tenant, **changes))
            )


@pytest.mark.parametrize(
    "changes",
    [
        {"embedding_generation": 0},
        {"embedding_dimension": 0},
        {"embedding_version": " "},
        {"provider_type": " provider"},
        {"provider_model_name": "name "},
        {"status": "indexed"},
        {"status": "processing"},
        {"status": "completed", "started_at": START},
        {"status": "failed", "finished_at": FINISH},
        {"started_at": START},
        {"status": "failed", "finished_at": FINISH, "failure_code": "bad-code"},
        {"status": "processing", "started_at": NOW - timedelta(seconds=1)},
        {"status": "failed", "finished_at": NOW, "failure_code": "FAILED"},
        {"organization_id": None},
        {"created_at": None},
    ],
)
def test_database_rejects_invalid_lifecycle_snapshots(context, changes):
    with pytest.raises(IntegrityError), context.engine.begin() as connection:
        connection.execute(
            insert(GenerationRow).values(**row_values(context.tenant, **changes))
        )


def test_database_uniqueness_history_and_model_neutral_headers(context):
    with context.engine.begin() as connection:
        connection.execute(
            insert(GenerationRow).values(
                **row_values(
                    context.tenant,
                    provider_type="future-provider",
                    provider_model_name="future-model",
                    embedding_dimension=768,
                )
            )
        )
    for changes in ({}, {"embedding_generation": 2}):
        with pytest.raises(IntegrityError), context.engine.begin() as connection:
            connection.execute(
                insert(GenerationRow).values(**row_values(context.tenant, **changes))
            )
    with context.engine.begin() as connection:
        connection.execute(
            update(GenerationRow).values(
                status="failed", finished_at=FINISH, failure_code="FAILED"
            )
        )
        connection.execute(
            insert(GenerationRow).values(
                **row_values(context.tenant, embedding_generation=2)
            )
        )


def test_configured_model_deletion_reports_existing_reference_conflict(context):
    create(context)
    with pytest.raises(ModelProviderDeleteRestrictedError, match="still referenced"):
        asyncio.run(
            SqlAlchemyModelProviderPersistence(context.sessions).delete_model(
                organization_public_id=context.tenant.generation.organization_public_id,
                model_id=ConfiguredModelId(
                    context.tenant.generation.configured_model_public_id
                ),
            )
        )
    assert read(context, context.tenant.generation) is not None


def data_snapshot(engine: Engine) -> dict[str, list[object]]:
    names = set(inspect(engine).get_table_names()) - {"indexing_generations"}
    quote = engine.dialect.identifier_preparer.quote
    with engine.connect() as connection:
        return {
            table.name: list(
                connection.scalars(
                    text(
                        f"SELECT to_jsonb(t) FROM {quote(table.name)} AS t ORDER BY "
                        + ", ".join(
                            quote(column.name) for column in table.primary_key.columns
                        )
                    )
                )
            )
            for table in Base.metadata.sorted_tables
            if table.name in names
        }


def test_migration_upgrade_downgrade_reupgrade_preserves_sources_and_legacy_vectors(
    migrated_database, persistence_async_session_factory
):
    config, engine = migrated_database
    command.upgrade(config, PREVIOUS)
    tenant = seed(engine)
    with engine.begin() as connection:
        connection.execute(
            insert(ChunkEmbedding).values(
                organization_id=tenant.organization_id,
                chunk_id=tenant.chunk_ids[0],
                configured_model_id=tenant.model_id,
                model_type="embedding",
                provider_type="openai",
                provider_model_name="text-embedding-3-small",
                embedding_dimension=1536,
                embedding_generation=5,
                embedding_version="legacy",
                embedding=list(VECTOR),
            )
        )
    before = data_snapshot(engine)
    command.upgrade(config, "head")
    assert data_snapshot(engine) == before
    inspector = inspect(engine)
    assert {c["name"] for c in inspector.get_columns("indexing_generations")} == set(
        GenerationRow.__table__.columns.keys()
    )
    assert {
        fk["name"] for fk in inspector.get_foreign_keys("indexing_generations")
    } == {
        "fk_indexing_generations_chunk_set",
        "fk_indexing_generations_tenant_embedding_model",
    }
    assert all(
        fk["options"]["ondelete"] == "RESTRICT"
        for fk in inspector.get_foreign_keys("indexing_generations")
    )
    assert set(
        inspector.get_pk_constraint("indexing_generations")["constrained_columns"]
    ) == {
        "organization_id",
        "document_id",
        "configured_model_id",
        "embedding_generation",
    }
    assert {
        check["name"]
        for check in inspector.get_check_constraints("indexing_generations")
    } == {
        c.name
        for c in GenerationRow.__table__.constraints
        if c.__class__.__name__ == "CheckConstraint"
    }
    assert [i["name"] for i in inspector.get_indexes("indexing_generations")] == [
        "uq_indexing_generations_active"
    ]
    persistence = SqlAlchemyIndexingPersistence(persistence_async_session_factory)
    with pytest.raises(IndexingConflictError):
        asyncio.run(
            persistence.create_generation(
                replace(tenant.generation, embedding_generation=5)
            )
        )
    asyncio.run(
        persistence.create_generation(
            replace(tenant.generation, embedding_generation=6)
        )
    )
    command.downgrade(config, PREVIOUS)
    assert "indexing_generations" not in inspect(engine).get_table_names()
    assert data_snapshot(engine) == before
    command.upgrade(config, "head")
    assert data_snapshot(engine) == before
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(GenerationRow)) == 0
        assert (
            connection.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname='vector'")
            )
            == "0.8.7"
        )


def test_failed_migration_rolls_back_new_schema_and_preserves_previous_revision(
    migrated_database, monkeypatch
):
    config, engine = migrated_database
    command.upgrade(config, PREVIOUS)
    seed(engine)
    before = data_snapshot(engine)
    original = Operations.create_index

    def broken(self, name, *args, **kwargs):
        if name == "uq_indexing_generations_active":
            raise SQLAlchemyError("Synthetic migration failure")
        return original(self, name, *args, **kwargs)

    monkeypatch.setattr(Operations, "create_index", broken)
    with pytest.raises(SQLAlchemyError):
        command.upgrade(config, "head")
    assert "indexing_generations" not in inspect(engine).get_table_names()
    assert data_snapshot(engine) == before
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == PREVIOUS
        )
