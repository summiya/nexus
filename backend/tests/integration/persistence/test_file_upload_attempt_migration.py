from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text

ATTEMPT_REVISION = "20260925_0009"
REMOVAL_REVISION = "20260925_0010"
CREATED_AT = datetime(2026, 9, 25, 12, tzinfo=UTC)


def _seed_file_and_attempt(engine: Engine) -> tuple[int, int]:
    with engine.begin() as connection:
        organization_id = connection.execute(
            text(
                """
                INSERT INTO organizations (
                    public_id, name, slug, status, settings_json
                )
                VALUES (
                    :public_id, 'Files', :slug, 'active',
                    CAST(:settings_json AS JSONB)
                )
                RETURNING id
                """
            ),
            {
                "public_id": str(uuid.uuid4()),
                "slug": f"files-{uuid.uuid4().hex[:12]}",
                "settings_json": json.dumps({}),
            },
        ).scalar_one()
        user_id = connection.execute(
            text(
                """
                INSERT INTO users (public_id, organization_id, email, status)
                VALUES (:public_id, :organization_id, :email, 'active')
                RETURNING id
                """
            ),
            {
                "public_id": str(uuid.uuid4()),
                "organization_id": organization_id,
                "email": f"{uuid.uuid4().hex}@example.com",
            },
        ).scalar_one()
        file_id = connection.execute(
            text(
                """
                INSERT INTO files (
                    public_id, organization_id, created_by_user_id,
                    original_name, mime_type, size_bytes, storage_key,
                    storage_status, checksum_sha256
                )
                VALUES (
                    :public_id, :organization_id, :user_id,
                    'report.pdf', 'application/pdf', NULL, :storage_key,
                    'pending', NULL
                )
                RETURNING id
                """
            ),
            {
                "public_id": str(uuid.uuid4()),
                "organization_id": organization_id,
                "user_id": user_id,
                "storage_key": f"files/{uuid.uuid4().hex}",
            },
        ).scalar_one()
        attempt_id = connection.execute(
            text(
                """
                INSERT INTO file_upload_attempts (
                    file_id, organization_id, declared_size_bytes,
                    grant_expires_at, created_at
                )
                VALUES (
                    :file_id, :organization_id, 42,
                    :grant_expires_at, :created_at
                )
                RETURNING id
                """
            ),
            {
                "file_id": file_id,
                "organization_id": organization_id,
                "grant_expires_at": CREATED_AT + timedelta(minutes=10),
                "created_at": CREATED_AT,
            },
        ).scalar_one()
    return file_id, attempt_id


def _assert_attempt_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    columns = {
        column["name"]: column
        for column in inspector.get_columns("file_upload_attempts")
    }
    assert set(columns) == {
        "id",
        "file_id",
        "organization_id",
        "declared_size_bytes",
        "grant_expires_at",
        "created_at",
    }
    assert inspector.get_pk_constraint("file_upload_attempts")["name"] == (
        "pk_file_upload_attempts"
    )
    foreign_keys = inspector.get_foreign_keys("file_upload_attempts")
    assert len(foreign_keys) == 1
    assert foreign_keys[0]["name"] == (
        "fk_file_upload_attempts_file_organization_files"
    )
    assert foreign_keys[0]["constrained_columns"] == [
        "file_id",
        "organization_id",
    ]
    assert foreign_keys[0]["referred_columns"] == ["id", "organization_id"]
    assert foreign_keys[0]["options"]["ondelete"] == "CASCADE"
    check_names = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("file_upload_attempts")
    }
    assert check_names == {
        "ck_file_upload_attempts_declared_size_bytes_nonnegative",
        "ck_file_upload_attempts_grant_expires_after_created_at",
    }
    indexes = {
        index["name"]: index
        for index in inspector.get_indexes("file_upload_attempts")
        if index.get("duplicates_constraint") is None
    }
    assert indexes["ix_file_upload_attempts_organization_file_created_at"][
        "column_names"
    ] == ["organization_id", "file_id", "created_at"]


def test_0009_contains_the_historical_upload_attempt_schema(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database

    command.upgrade(config, ATTEMPT_REVISION)

    assert "file_upload_attempts" in inspect(engine).get_table_names()
    _assert_attempt_schema(engine)


def test_0010_removes_attempts_without_removing_files(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, ATTEMPT_REVISION)
    file_id, _ = _seed_file_and_attempt(engine)

    command.upgrade(config, REMOVAL_REVISION)

    assert "file_upload_attempts" not in inspect(engine).get_table_names()
    assert "files" in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM files WHERE id = :id"),
                {"id": file_id},
            )
            == 1
        )


def test_0010_downgrade_recreates_the_exact_previous_schema(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, REMOVAL_REVISION)

    command.downgrade(config, ATTEMPT_REVISION)

    assert "files" in inspect(engine).get_table_names()
    assert "file_upload_attempts" in inspect(engine).get_table_names()
    _assert_attempt_schema(engine)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM file_upload_attempts")) == 0
