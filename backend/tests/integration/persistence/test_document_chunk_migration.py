from alembic import command
from sqlalchemy import inspect

from nexus.infrastructure.persistence.models.document_chunk import (
    DocumentChunk,
    DocumentChunkSet,
)


def test_chunk_migration_upgrade_downgrade_and_only_required_indexes(migrated_database):
    config, engine = migrated_database
    command.upgrade(config, "20261005_0017")
    before = [
        {**column, "type": str(column["type"])}
        for column in inspect(engine).get_columns("documents")
    ]
    assert "document_chunks" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    inspector = inspect(engine)
    for model in (DocumentChunkSet, DocumentChunk):
        table = model.__tablename__
        assert {c["name"] for c in inspector.get_columns(table)} == set(
            model.__table__.columns.keys()
        )
        assert {c["name"] for c in inspector.get_check_constraints(table)} == {
            c.name
            for c in model.__table__.constraints
            if c.__class__.__name__ == "CheckConstraint"
        }
        (foreign_key,) = inspector.get_foreign_keys(table)
        assert foreign_key["constrained_columns"] == ["document_id", "organization_id"]
        assert foreign_key["referred_columns"] == (
            ["id", "organization_id"]
            if table == "document_chunk_sets"
            else ["document_id", "organization_id"]
        )
        assert foreign_key["options"]["ondelete"] == "RESTRICT"
        # Only the unique constraint backing index; no search/provenance indexes.
        assert all(
            index.get("duplicates_constraint") for index in inspector.get_indexes(table)
        )
    assert {
        tuple(c["column_names"])
        for c in inspector.get_unique_constraints("document_chunk_sets")
    } == {("document_id", "organization_id")}
    assert {
        tuple(c["column_names"])
        for c in inspector.get_unique_constraints("document_chunks")
    } == {("document_id", "chunk_index")}
    assert [
        {**column, "type": str(column["type"])}
        for column in inspect(engine).get_columns("documents")
    ] == before
    command.downgrade(config, "20261005_0017")
    assert "document_chunk_sets" not in inspect(engine).get_table_names()
    assert "document_chunks" not in inspect(engine).get_table_names()
    assert "documents" in inspect(engine).get_table_names()
    command.upgrade(config, "head")
