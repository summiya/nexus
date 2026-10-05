from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text


def test_document_request_migration_upgrade_and_downgrade(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, "20261001_0015")
    assert "document_processing_requests" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    inspector = inspect(engine)
    assert {
        column["name"]
        for column in inspector.get_columns("document_processing_requests")
    } == {
        "id",
        "public_id",
        "organization_id",
        "source_file_id",
        "document_id",
        "source_entity_tag",
        "expected_size_bytes",
        "created_at",
        "dispatched_at",
        "dispatch_lease_token",
        "dispatch_lease_until",
        "dispatch_next_attempt_at",
        "dispatch_attempts",
    }
    constraints = inspector.get_foreign_keys("document_processing_requests")
    assert len(constraints) == 1
    assert constraints[0]["constrained_columns"] == [
        "document_id",
        "organization_id",
        "source_file_id",
    ]
    assert constraints[0]["referred_columns"] == [
        "id",
        "organization_id",
        "source_file_id",
    ]
    assert {
        item["name"]
        for item in inspector.get_unique_constraints("document_processing_requests")
    } == {
        "uq_document_requests_public_id",
        "uq_document_requests_initial_file",
        "uq_document_requests_document",
    }
    with engine.connect() as connection:
        index = connection.execute(
            text(
                "SELECT indexdef FROM pg_indexes WHERE schemaname = current_schema() "
                "AND indexname = 'ix_document_requests_pending'"
            )
        ).scalar_one()
    assert "dispatched_at IS NULL" in index
    assert "dispatch_next_attempt_at" in index
    command.downgrade(config, "20261005_0016")
    assert "dispatch_lease_token" not in {
        column["name"]
        for column in inspect(engine).get_columns("document_processing_requests")
    }
    command.upgrade(config, "head")
    command.downgrade(config, "20261001_0015")
    assert "document_processing_requests" not in inspect(engine).get_table_names()
    assert "uq_documents_id_organization_source" not in {
        item["name"] for item in inspect(engine).get_unique_constraints("documents")
    }
    assert "documents" in inspect(engine).get_table_names()
