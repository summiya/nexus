from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import Engine, delete, func, insert, inspect, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from tests.integration.helpers import seed_file

from nexus.infrastructure.persistence.authorization import SqlAlchemyPermissionChecker
from nexus.infrastructure.persistence.models import (
    ChunkEmbedding,
    ConfiguredModel,
    Document,
    DocumentChunk,
    DocumentChunkSet,
    File,
    ModelProvider,
    Organization,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)

PREVIOUS = "20261007_0019"
NOW = datetime(2026, 11, 3, tzinfo=UTC)
VECTOR = [1.0] + [0.0] * 1535


@dataclass(frozen=True)
class Tenant:
    organization_id: int
    user_id: int
    file_id: int
    document_id: int
    chunk_id: int
    provider_id: int
    model_id: int


@dataclass(frozen=True)
class Context:
    engine: Engine
    tenant: Tenant
    other: Tenant
    chat_model_id: int
    reranker_model_id: int


def seed_tenant(engine: Engine) -> Tenant:
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
                source_entity_tag="admitted-etag",
                extractor_id="extractor",
                extractor_version="1",
                normalizer_id="normalizer",
                normalizer_version="1",
                segmenter_id="segmenter",
                segmenter_version="1",
                preferred_chunk_bytes=1024,
                max_chunk_bytes=4096,
                max_source_contributions=128,
                chunk_count=1,
            )
        )
        session.flush()
        chunk = DocumentChunk(
            document_id=document.id,
            organization_id=file.organization_id,
            chunk_index=0,
            text="Authoritative chunk",
            kind="text",
            section_path=[],
            contributions=[
                {
                    "source_block_index": 0,
                    "kind": "text",
                    "start_line": 1,
                    "end_line": 1,
                    "page_number": None,
                    "list_item": None,
                    "quote_depth": None,
                    "text_start": None,
                    "text_end": None,
                }
            ],
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
        session.add_all([chunk, model])
        session.flush()
        result = Tenant(
            file.organization_id,
            file.created_by_user_id,
            file.id,
            document.id,
            chunk.id,
            provider.id,
            model.id,
        )
        session.commit()
        return result


def add_model(engine: Engine, tenant: Tenant, model_type: str) -> int:
    with Session(engine) as session:
        provider_id = tenant.provider_id
        if model_type == "embedding":
            provider = ModelProvider(
                public_id=uuid4(),
                organization_id=tenant.organization_id,
                provider_type="openai",
                display_name="Replacement OpenAI",
                settings_json={},
            )
            session.add(provider)
            session.flush()
            provider_id = provider.id
        model = ConfiguredModel(
            public_id=uuid4(),
            organization_id=tenant.organization_id,
            provider_id=provider_id,
            provider_model_name="text-embedding-3-small"
            if model_type == "embedding"
            else f"test-{model_type}",
            display_name=model_type,
            model_type=model_type,
            capabilities=[],
            embedding_dimension=1536 if model_type == "embedding" else None,
        )
        session.add(model)
        session.flush()
        identity = model.id
        session.commit()
        return identity


@pytest.fixture
def context(migrated_database) -> Context:
    config, engine = migrated_database
    command.upgrade(config, "head")
    tenant, other = seed_tenant(engine), seed_tenant(engine)
    return Context(
        engine,
        tenant,
        other,
        add_model(engine, tenant, "chat"),
        add_model(engine, tenant, "reranker"),
    )


def values(tenant: Tenant, **changes: object) -> dict[str, object]:
    return {
        "organization_id": tenant.organization_id,
        "chunk_id": tenant.chunk_id,
        "configured_model_id": tenant.model_id,
        "model_type": "embedding",
        "provider_type": "openai",
        "provider_model_name": "text-embedding-3-small",
        "embedding_dimension": 1536,
        "embedding_generation": 1,
        "embedding_version": "rf-v1",
        "embedding": VECTOR,
        **changes,
    }


def write(context: Context, **changes: object) -> int:
    with context.engine.begin() as connection:
        return connection.execute(
            insert(ChunkEmbedding)
            .values(**values(context.tenant, **changes))
            .returning(ChunkEmbedding.id)
        ).scalar_one()


def reject(context: Context, state: str, **changes: object) -> None:
    with pytest.raises(DBAPIError) as captured:
        write(context, **changes)
    assert captured.value.orig.sqlstate == state


def test_schema_matches_orm_and_has_only_required_btree_indexes(context):
    inspector = inspect(context.engine)
    columns = inspector.get_columns("chunk_embeddings")
    assert {c["name"] for c in columns} == set(ChunkEmbedding.__table__.columns.keys())
    assert all(not c["nullable"] for c in columns)
    assert (
        str(next(c["type"] for c in columns if c["name"] == "embedding"))
        == "VECTOR(1536)"
    )
    assert not {"user_id", "document_id", "text", "acl", "role_id"}.intersection(
        c["name"] for c in columns
    )
    assert {c["name"] for c in inspector.get_check_constraints("chunk_embeddings")} == {
        c.name
        for c in ChunkEmbedding.__table__.constraints
        if c.__class__.__name__ == "CheckConstraint"
    }
    foreign_keys = {
        fk["name"]: fk for fk in inspector.get_foreign_keys("chunk_embeddings")
    }
    assert set(foreign_keys) == {
        "fk_chunk_embeddings_organization",
        "fk_chunk_embeddings_chunk_organization",
        "fk_chunk_embeddings_tenant_embedding_model",
    }
    chunk_key = foreign_keys["fk_chunk_embeddings_chunk_organization"]
    assert chunk_key["referred_table"] == "document_chunks"
    assert chunk_key["constrained_columns"] == ["chunk_id", "organization_id"]
    assert chunk_key["referred_columns"] == ["id", "organization_id"]
    model_key = foreign_keys["fk_chunk_embeddings_tenant_embedding_model"]
    assert model_key["referred_table"] == "configured_models"
    assert model_key["constrained_columns"] == [
        "organization_id",
        "model_type",
        "configured_model_id",
    ]
    assert model_key["referred_columns"] == ["organization_id", "model_type", "id"]
    organization_key = foreign_keys["fk_chunk_embeddings_organization"]
    assert organization_key["referred_table"] == "organizations"
    assert organization_key["constrained_columns"] == ["organization_id"]
    assert organization_key["referred_columns"] == ["id"]
    assert all(fk["options"]["ondelete"] == "RESTRICT" for fk in foreign_keys.values())
    indexes = inspector.get_indexes("chunk_embeddings")
    assert {i["name"] for i in indexes if not i.get("duplicates_constraint")} == {
        "ix_chunk_embeddings_organization_model_generation"
    }
    lookup = next(i for i in indexes if not i.get("duplicates_constraint"))
    assert lookup["column_names"] == [
        "organization_id",
        "configured_model_id",
        "embedding_generation",
    ]
    assert {
        tuple(c["column_names"])
        for c in inspector.get_unique_constraints("chunk_embeddings")
    } == {
        ("organization_id", "chunk_id", "configured_model_id", "embedding_generation")
    }
    with context.engine.connect() as connection:
        definitions = connection.scalars(
            text("SELECT indexdef FROM pg_indexes WHERE tablename = 'chunk_embeddings'")
        ).all()
        assert len(definitions) == 3
        assert all("USING btree" in definition for definition in definitions)


def test_round_trip_retains_authoritative_source_provenance_and_creator(context):
    identity = write(context)
    with Session(context.engine) as session:
        row = session.get(ChunkEmbedding, identity)
        assert row is not None
        assert row.embedding == VECTOR and isinstance(row.embedding, list)
        assert all(type(element) is float for element in row.embedding)
        assert row.created_at.tzinfo is not None
        source = session.execute(
            select(
                Document.public_id,
                Document.processing_version,
                DocumentChunk.chunk_index,
                DocumentChunk.text,
                DocumentChunk.contributions,
                DocumentChunkSet.source_entity_tag,
                File.created_by_user_id,
            )
            .select_from(ChunkEmbedding)
            .join(
                DocumentChunk,
                (DocumentChunk.id == ChunkEmbedding.chunk_id)
                & (DocumentChunk.organization_id == ChunkEmbedding.organization_id),
            )
            .join(
                Document,
                (Document.id == DocumentChunk.document_id)
                & (Document.organization_id == DocumentChunk.organization_id),
            )
            .join(
                DocumentChunkSet,
                (DocumentChunkSet.document_id == Document.id)
                & (DocumentChunkSet.organization_id == Document.organization_id),
            )
            .join(
                File,
                (File.id == Document.source_file_id)
                & (File.organization_id == Document.organization_id),
            )
            .where(ChunkEmbedding.id == identity)
        ).one()
        assert source.processing_version == "dp-v1"
        assert source.chunk_index == 0 and source.text == "Authoritative chunk"
        assert source.contributions[0]["start_line"] == 1
        assert source.source_entity_tag == "admitted-etag"
        assert source.created_by_user_id == context.tenant.user_id


@pytest.mark.parametrize(
    "field",
    [
        "organization_id",
        "chunk_id",
        "configured_model_id",
        "model_type",
        "provider_type",
        "provider_model_name",
        "embedding_dimension",
        "embedding_generation",
        "embedding_version",
        "embedding",
        "created_at",
    ],
)
def test_required_fields_cannot_be_null(context, field):
    reject(context, "23502", **{field: None})


@pytest.mark.parametrize(
    "relationship",
    [
        "foreign-chunk",
        "foreign-model",
        "foreign-tenant",
        "missing-chunk",
        "missing-model",
        "missing-organization",
    ],
)
def test_foreign_and_missing_relationships_are_rejected(context, relationship):
    changes = {
        "foreign-chunk": {"chunk_id": context.other.chunk_id},
        "foreign-model": {"configured_model_id": context.other.model_id},
        "foreign-tenant": {"organization_id": context.other.organization_id},
        "missing-chunk": {"chunk_id": 2**62},
        "missing-model": {"configured_model_id": 2**62},
        "missing-organization": {"organization_id": 2**62},
    }[relationship]
    reject(context, "23503", **changes)
    with context.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ChunkEmbedding)) == 0


@pytest.mark.parametrize("kind", ["chat", "reranker"])
def test_embedding_discriminator_cannot_reference_other_model_types(context, kind):
    identity = context.chat_model_id if kind == "chat" else context.reranker_model_id
    reject(context, "23503", configured_model_id=identity)
    reject(context, "23514", configured_model_id=identity, model_type=kind)


@pytest.mark.parametrize(
    "changes",
    [
        {"embedding_dimension": 0},
        {"embedding_dimension": 1535},
        {"embedding_dimension": 3072},
        {"embedding_generation": 0},
        {"embedding_generation": -1},
        {"embedding_version": ""},
        {"embedding_version": " \n"},
        {"embedding_version": " v1"},
        {"embedding_version": "v1\n"},
        {"provider_type": "gemini"},
        {"provider_model_name": "text-embedding-3-large"},
    ],
)
def test_declared_v1_metadata_is_constrained(context, changes):
    reject(context, "23514", **changes)


@pytest.mark.parametrize("vector", [[0.0] * 1536, [1e-100] * 1536])
def test_zero_and_float32_underflow_vectors_are_rejected(context, vector):
    reject(context, "23514", embedding=vector)


@pytest.mark.parametrize(
    "vector",
    [
        [1.0] * 1535,
        [1.0] * 1537,
        [float("nan")] + [0.0] * 1535,
        [float("inf")] + [0.0] * 1535,
        [float("-inf")] + [0.0] * 1535,
        [1e100] + [0.0] * 1535,
    ],
)
def test_database_rejects_invalid_vector_width_or_numeric_values(context, vector):
    with pytest.raises(DBAPIError) as captured:
        write(context, embedding=vector)
    assert captured.value.orig.sqlstate.startswith("22")


def test_generations_are_unique_without_preventing_version_or_model_replacement(
    context,
):
    write(context)
    reject(context, "23505")
    write(context, embedding_generation=2, embedding_version="rf-v2")
    replacement = add_model(context.engine, context.tenant, "embedding")
    # A second configured model can hold historical vectors at the same width.
    write(context, configured_model_id=replacement)
    with context.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ChunkEmbedding)) == 3


@pytest.mark.parametrize("parent", [DocumentChunk, ConfiguredModel, Organization])
def test_referenced_parents_cannot_be_deleted(context, parent):
    write(context)
    identity = {
        DocumentChunk: context.tenant.chunk_id,
        ConfiguredModel: context.tenant.model_id,
        Organization: context.tenant.organization_id,
    }[parent]
    with pytest.raises(IntegrityError), context.engine.begin() as connection:
        connection.execute(delete(parent).where(parent.id == identity))


@pytest.mark.parametrize(
    "relationship", ["chunk-document", "set-document", "document-file"]
)
def test_authoritative_chain_cannot_be_reassigned_to_another_tenant(
    context, relationship
):
    write(context)
    statement = {
        "chunk-document": update(DocumentChunk)
        .where(DocumentChunk.id == context.tenant.chunk_id)
        .values(document_id=context.other.document_id),
        "set-document": update(DocumentChunkSet)
        .where(DocumentChunkSet.document_id == context.tenant.document_id)
        .values(organization_id=context.other.organization_id),
        "document-file": update(Document)
        .where(Document.id == context.tenant.document_id)
        .values(source_file_id=context.other.file_id),
    }[relationship]
    with pytest.raises(IntegrityError), context.engine.begin() as connection:
        connection.execute(statement)


def test_snapshots_are_historical_not_authenticated_against_live_configuration(context):
    identity = write(context)
    with context.engine.begin() as connection:
        connection.execute(
            update(ConfiguredModel)
            .where(ConfiguredModel.id == context.tenant.model_id)
            .values(
                provider_model_name="changed-model",
                embedding_dimension=768,
                enabled=False,
            )
        )
        connection.execute(
            update(ModelProvider)
            .where(ModelProvider.id == context.tenant.provider_id)
            .values(provider_type="gemini")
        )
    # The FK still authenticates tenant + embedding model type only. Existing
    # invocation snapshots must survive configuration edits; a future trusted
    # writer must obtain them from the target actually used, not client input.
    with Session(context.engine) as session:
        row = session.get(ChunkEmbedding, identity)
        assert (
            row.provider_type,
            row.provider_model_name,
            row.embedding_dimension,
        ) == (
            "openai",
            "text-embedding-3-small",
            1536,
        )


def test_permission_revocation_neither_grants_vector_access_nor_rewrites_vectors(
    context,
    persistence_async_session_factory,
):
    identity = write(context)
    with Session(context.engine) as session:
        organization = session.get(Organization, context.tenant.organization_id)
        source = session.get(File, context.tenant.file_id)
        permission = session.scalar(
            select(Permission).where(Permission.key == "files.read")
        )
        assert (
            organization is not None and source is not None and permission is not None
        )
        user = session.get(User, context.tenant.user_id)
        assert user is not None
        organization_public_id, user_public_id = organization.public_id, user.public_id
        role = Role(organization_id=organization.id, name="Reader")
        session.add(role)
        session.flush()
        session.add_all(
            [
                UserRole(
                    organization_id=organization.id, user_id=user.id, role_id=role.id
                ),
                RolePermission(role_id=role.id, permission_id=permission.id),
            ]
        )
        role_id, permission_id = role.id, permission.id
        session.commit()
    checker = SqlAlchemyPermissionChecker(persistence_async_session_factory)

    def allowed():
        return asyncio.run(
            checker.has_permission(
                organization_public_id=organization_public_id,
                user_public_id=user_public_id,
                permission_key="files.read",
            )
        )

    assert allowed()
    with context.engine.begin() as connection:
        connection.execute(
            delete(RolePermission).where(
                RolePermission.role_id == role_id,
                RolePermission.permission_id == permission_id,
            )
        )
    assert not allowed()
    with Session(context.engine) as session:
        row = session.get(ChunkEmbedding, identity)
        assert row.embedding == VECTOR and row.embedding_generation == 1
        assert session.scalar(select(func.count()).select_from(ChunkEmbedding)) == 1


def parent_snapshot(engine: Engine) -> dict[str, list[dict[str, object]]]:
    with engine.connect() as connection:
        return {
            model.__tablename__: [
                dict(row)
                for row in connection.execute(
                    select(model.__table__).order_by(
                        *model.__table__.primary_key.columns
                    )
                ).mappings()
            ]
            for model in (
                Organization,
                File,
                Document,
                DocumentChunkSet,
                DocumentChunk,
                ModelProvider,
                ConfiguredModel,
            )
        }


def test_upgrade_downgrade_and_reupgrade_preserve_parents_and_shared_extension(
    migrated_database,
):
    config, engine = migrated_database
    command.upgrade(config, PREVIOUS)
    tenant = seed_tenant(engine)
    before = parent_snapshot(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION vector"))
    command.upgrade(config, "head")
    assert parent_snapshot(engine) == before
    with engine.begin() as connection:
        connection.execute(insert(ChunkEmbedding).values(**values(tenant)))
    command.downgrade(config, PREVIOUS)
    assert "chunk_embeddings" not in inspect(engine).get_table_names()
    assert parent_snapshot(engine) == before
    assert {
        tuple(c["column_names"])
        for c in inspect(engine).get_unique_constraints("document_chunks")
    } == {
        ("document_id", "chunk_index"),
    }
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        )
    command.upgrade(config, "head")
    assert parent_snapshot(engine) == before
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ChunkEmbedding)) == 0


def test_failed_upgrade_rolls_back_extension_and_new_schema_atomically(
    migrated_database,
):
    config, engine = migrated_database
    command.upgrade(config, PREVIOUS)
    seed_tenant(engine)
    before = parent_snapshot(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE document_chunks ADD CONSTRAINT "
                "uq_document_chunks_id_organization_id UNIQUE (id, organization_id)"
            )
        )
    with pytest.raises(DBAPIError):
        command.upgrade(config, "head")
    assert "chunk_embeddings" not in inspect(engine).get_table_names()
    assert parent_snapshot(engine) == before
    with engine.begin() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == PREVIOUS
        )
        assert not connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        )
        connection.execute(
            text(
                "ALTER TABLE document_chunks DROP CONSTRAINT "
                "uq_document_chunks_id_organization_id"
            )
        )
    command.upgrade(config, "head")
