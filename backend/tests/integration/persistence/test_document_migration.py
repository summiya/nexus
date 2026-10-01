from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text


def test_document_migration_upgrade_and_downgrade(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, "20260929_0014")
    assert "documents" not in inspect(engine).get_table_names()

    command.upgrade(config, "20261001_0015")

    inspector = inspect(engine)
    assert {column["name"] for column in inspector.get_columns("documents")} == {
        "id",
        "public_id",
        "organization_id",
        "source_file_id",
        "status",
        "processing_version",
        "extractor_version",
        "processing_started_at",
        "processing_completed_at",
        "failed_at",
        "failure_code",
        "failure_safe_message",
        "created_at",
    }
    assert {item["name"] for item in inspector.get_foreign_keys("documents")} == {
        "fk_documents_organization_id_organizations",
        "fk_documents_source_file_organization_files",
    }
    assert {item["name"] for item in inspector.get_check_constraints("documents")} == {
        "ck_documents_extractor_version",
        "ck_documents_failure_code_format",
        "ck_documents_failure_message_nonblank",
        "ck_documents_lifecycle_metadata",
        "ck_documents_processing_version",
        "ck_documents_public_id_nonzero",
        "ck_documents_status",
        "ck_documents_timestamp_order",
    }
    unique_constraints = {
        item["name"]: item["column_names"]
        for item in inspector.get_unique_constraints("documents")
    }
    assert unique_constraints == {
        "uq_documents_id_organization_id": ["id", "organization_id"],
        "uq_documents_public_id": ["public_id"],
    }
    with engine.connect() as connection:
        active_index = connection.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = current_schema() "
                "AND tablename = 'documents' "
                "AND indexname = 'uq_documents_active_source_file_id'"
            )
        ).scalar_one()
    assert "UNIQUE INDEX" in active_index
    assert "status" in active_index
    assert "queued" in active_index
    assert "processing" in active_index

    command.downgrade(config, "20260929_0014")
    assert "documents" not in inspect(engine).get_table_names()
