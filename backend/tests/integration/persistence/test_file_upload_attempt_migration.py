from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError

PREVIOUS_HEAD = "20260924_0008"
CREATED_AT = datetime(2026, 9, 25, 12, tzinfo=UTC)
GRANT_EXPIRES_AT = CREATED_AT + timedelta(minutes=15)


def _upgrade(config: Config) -> None:
    command.upgrade(config, "head")


def _insert_organization(connection: sa.Connection, slug: str) -> int:
    return connection.execute(
        text(
            """
            INSERT INTO organizations (
                public_id, name, slug, status, settings_json
            )
            VALUES (
                :public_id, :name, :slug, 'active', CAST(:settings_json AS JSONB)
            )
            RETURNING id
            """
        ),
        {
            "public_id": str(uuid.uuid4()),
            "name": f"Organization {slug}",
            "slug": slug,
            "settings_json": json.dumps({}),
        },
    ).scalar_one()


def _insert_user(
    connection: sa.Connection,
    organization_id: int,
    email: str,
) -> int:
    return connection.execute(
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
            "email": email,
        },
    ).scalar_one()


def _insert_file(
    connection: sa.Connection,
    organization_id: int,
    created_by_user_id: int,
) -> int:
    return connection.execute(
        text(
            """
            INSERT INTO files (
                public_id,
                organization_id,
                created_by_user_id,
                original_name,
                mime_type,
                size_bytes,
                storage_key,
                storage_status,
                checksum_sha256
            )
            VALUES (
                :public_id,
                :organization_id,
                :created_by_user_id,
                'report.pdf',
                'application/pdf',
                NULL,
                :storage_key,
                'pending',
                NULL
            )
            RETURNING id
            """
        ),
        {
            "public_id": str(uuid.uuid4()),
            "organization_id": organization_id,
            "created_by_user_id": created_by_user_id,
            "storage_key": f"files/{uuid.uuid4().hex}",
        },
    ).scalar_one()


def _insert_attempt(
    connection: sa.Connection,
    *,
    file_id: int,
    organization_id: int,
    declared_size_bytes: int = 42,
    grant_expires_at: datetime = GRANT_EXPIRES_AT,
    created_at: datetime = CREATED_AT,
) -> int:
    return connection.execute(
        text(
            """
            INSERT INTO file_upload_attempts (
                file_id,
                organization_id,
                declared_size_bytes,
                grant_expires_at,
                created_at
            )
            VALUES (
                :file_id,
                :organization_id,
                :declared_size_bytes,
                :grant_expires_at,
                :created_at
            )
            RETURNING id
            """
        ),
        {
            "file_id": file_id,
            "organization_id": organization_id,
            "declared_size_bytes": declared_size_bytes,
            "grant_expires_at": grant_expires_at,
            "created_at": created_at,
        },
    ).scalar_one()


def _seed_file(connection: sa.Connection, slug: str) -> tuple[int, int]:
    organization_id = _insert_organization(connection, slug)
    user_id = _insert_user(connection, organization_id, f"{slug}@example.com")
    return organization_id, _insert_file(connection, organization_id, user_id)


def test_upgrade_creates_file_upload_attempt_schema(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    _upgrade(config)
    inspector = inspect(engine)

    assert "file_upload_attempts" in inspector.get_table_names()
    primary_key = inspector.get_pk_constraint("file_upload_attempts")
    assert primary_key["name"] == "pk_file_upload_attempts"
    assert primary_key["constrained_columns"] == ["id"]

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
    assert all(column["nullable"] is False for column in columns.values())
    assert isinstance(columns["id"]["type"], sa.BigInteger)
    assert isinstance(columns["file_id"]["type"], sa.BigInteger)
    assert isinstance(columns["organization_id"]["type"], sa.BigInteger)
    assert isinstance(columns["declared_size_bytes"]["type"], sa.BigInteger)
    assert isinstance(columns["grant_expires_at"]["type"], sa.DateTime)
    assert columns["grant_expires_at"]["type"].timezone is True
    assert isinstance(columns["created_at"]["type"], sa.DateTime)
    assert columns["created_at"]["type"].timezone is True

    assert inspector.get_unique_constraints("file_upload_attempts") == []
    foreign_keys = inspector.get_foreign_keys("file_upload_attempts")
    assert len(foreign_keys) == 1
    assert foreign_keys[0]["name"] == (
        "fk_file_upload_attempts_file_organization_files"
    )
    assert foreign_keys[0]["constrained_columns"] == [
        "file_id",
        "organization_id",
    ]
    assert foreign_keys[0]["referred_table"] == "files"
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
    assert set(indexes) == {
        "ix_file_upload_attempts_organization_file_created_at",
    }
    assert indexes["ix_file_upload_attempts_organization_file_created_at"][
        "column_names"
    ] == ["organization_id", "file_id", "created_at"]


def test_upload_attempt_allows_zero_size_and_multiple_attempts_per_file(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    _upgrade(config)

    with engine.begin() as connection:
        organization_id, file_id = _seed_file(connection, "multiple-attempts")
        first_id = _insert_attempt(
            connection,
            file_id=file_id,
            organization_id=organization_id,
            declared_size_bytes=0,
        )
        second_id = _insert_attempt(
            connection,
            file_id=file_id,
            organization_id=organization_id,
            declared_size_bytes=7,
            created_at=CREATED_AT + timedelta(seconds=1),
            grant_expires_at=GRANT_EXPIRES_AT + timedelta(seconds=1),
        )

    assert first_id != second_id


def test_upload_attempt_rejects_negative_declared_size(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    _upgrade(config)
    with engine.begin() as connection:
        organization_id, file_id = _seed_file(connection, "negative-size")

    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert_attempt(
            connection,
            file_id=file_id,
            organization_id=organization_id,
            declared_size_bytes=-1,
        )


@pytest.mark.parametrize(
    "grant_expires_at",
    [CREATED_AT, CREATED_AT - timedelta(microseconds=1)],
)
def test_upload_attempt_requires_expiration_after_creation(
    migrated_database: tuple[Config, Engine],
    grant_expires_at: datetime,
) -> None:
    config, engine = migrated_database
    _upgrade(config)
    with engine.begin() as connection:
        organization_id, file_id = _seed_file(connection, "invalid-expiration")

    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert_attempt(
            connection,
            file_id=file_id,
            organization_id=organization_id,
            grant_expires_at=grant_expires_at,
        )


def test_upload_attempt_file_reference_is_tenant_safe(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    _upgrade(config)
    with engine.begin() as connection:
        _, file_id = _seed_file(connection, "attempt-tenant-a")
        other_organization_id = _insert_organization(connection, "attempt-tenant-b")

    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert_attempt(
            connection,
            file_id=file_id,
            organization_id=other_organization_id,
        )


def test_deleting_file_cascades_to_upload_attempts(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    _upgrade(config)

    with engine.begin() as connection:
        organization_id, file_id = _seed_file(connection, "attempt-cascade")
        _insert_attempt(
            connection,
            file_id=file_id,
            organization_id=organization_id,
        )
        connection.execute(text("DELETE FROM files WHERE id = :id"), {"id": file_id})

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM file_upload_attempts")) == 0


def test_downgrade_preserves_files_and_reupgrade_restores_attempt_schema(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    _upgrade(config)

    command.downgrade(config, PREVIOUS_HEAD)

    table_names = inspect(engine).get_table_names()
    assert "files" in table_names
    assert "file_upload_attempts" not in table_names

    _upgrade(config)

    assert "file_upload_attempts" in inspect(engine).get_table_names()
