from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError

PREVIOUS_HEAD = "20260922_0007"


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


def _file_values(
    organization_id: int,
    created_by_user_id: int,
    **overrides: object,
) -> dict[str, object]:
    values: dict[str, object] = {
        "public_id": str(uuid.uuid4()),
        "organization_id": organization_id,
        "created_by_user_id": created_by_user_id,
        "original_name": "report.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 42,
        "storage_key": f"opaque-{uuid.uuid4()}",
        "storage_status": "available",
        "checksum_sha256": None,
    }
    values.update(overrides)
    return values


def _insert_file(
    connection: sa.Connection,
    values: Mapping[str, Any],
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
                :original_name,
                :mime_type,
                :size_bytes,
                :storage_key,
                :storage_status,
                :checksum_sha256
            )
            RETURNING id
            """
        ),
        values,
    ).scalar_one()


def test_upgrade_creates_file_schema(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    _upgrade(config)
    inspector = inspect(engine)

    assert "files" in inspector.get_table_names()
    primary_key = inspector.get_pk_constraint("files")
    assert primary_key["constrained_columns"] == ["id"]
    assert primary_key["name"] == "pk_files"

    columns = {column["name"]: column for column in inspector.get_columns("files")}
    assert columns["organization_id"]["nullable"] is False
    assert columns["created_by_user_id"]["nullable"] is False
    assert columns["size_bytes"]["nullable"] is True
    assert columns["checksum_sha256"]["nullable"] is True
    assert columns["created_at"]["default"] is not None
    assert columns["updated_at"]["default"] is not None

    unique_names = {
        constraint["name"] for constraint in inspector.get_unique_constraints("files")
    }
    assert unique_names == {
        "uq_files_public_id",
        "uq_files_id_organization_id",
        "uq_files_storage_key",
    }

    foreign_keys = {
        constraint["name"]: constraint
        for constraint in inspector.get_foreign_keys("files")
    }
    assert set(foreign_keys) == {
        "fk_files_organization_id_organizations",
        "fk_files_creator_organization_users",
    }
    assert (
        foreign_keys["fk_files_organization_id_organizations"]["options"]["ondelete"]
        == "RESTRICT"
    )
    assert foreign_keys["fk_files_creator_organization_users"][
        "constrained_columns"
    ] == ["created_by_user_id", "organization_id"]

    check_names = {
        constraint["name"] for constraint in inspector.get_check_constraints("files")
    }
    assert check_names == {
        "ck_files_original_name_nonblank",
        "ck_files_mime_type_nonblank",
        "ck_files_storage_key_nonblank",
        "ck_files_size_bytes_nonnegative",
        "ck_files_storage_status",
        "ck_files_checksum_sha256_format",
        "ck_files_available_size",
    }

    indexes = {
        index["name"]: index
        for index in inspector.get_indexes("files")
        if index.get("duplicates_constraint") is None
    }
    assert indexes["ix_files_organization_created_at_public_id"]["column_names"] == [
        "organization_id",
        "created_at",
        "public_id",
    ]


def test_file_constraints_allow_optional_checksum_for_available_file(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    _upgrade(config)

    with engine.begin() as connection:
        organization_id = _insert_organization(connection, "optional-checksum")
        user_id = _insert_user(connection, organization_id, "optional@example.com")
        file_id = _insert_file(
            connection,
            _file_values(
                organization_id,
                user_id,
                checksum_sha256=None,
            ),
        )
        timestamps = connection.execute(
            text("SELECT created_at, updated_at FROM files WHERE id = :file_id"),
            {"file_id": file_id},
        ).one()

    assert timestamps.created_at is not None
    assert timestamps.updated_at is not None


@pytest.mark.parametrize(
    "overrides",
    [
        {"storage_status": "unknown"},
        {"storage_status": "available", "size_bytes": None},
        {"size_bytes": -1},
        {"checksum_sha256": "A" * 64},
        {"checksum_sha256": "a" * 63},
        {"original_name": " "},
        {"mime_type": ""},
        {"storage_key": "\t"},
    ],
)
def test_file_check_constraints_reject_invalid_metadata(
    migrated_database: tuple[Config, Engine],
    overrides: dict[str, object],
) -> None:
    config, engine = migrated_database
    _upgrade(config)
    with engine.begin() as connection:
        organization_id = _insert_organization(connection, "invalid-metadata")
        user_id = _insert_user(connection, organization_id, "invalid@example.com")

    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert_file(
            connection,
            _file_values(organization_id, user_id, **overrides),
        )


def test_file_creator_must_belong_to_file_organization(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    _upgrade(config)
    with engine.begin() as connection:
        organization_id = _insert_organization(connection, "tenant-a")
        other_organization_id = _insert_organization(connection, "tenant-b")
        other_user_id = _insert_user(
            connection,
            other_organization_id,
            "other@example.com",
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert_file(
            connection,
            _file_values(organization_id, other_user_id),
        )

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM files")) == 0


@pytest.mark.parametrize("duplicate_field", ["public_id", "storage_key"])
def test_file_public_identity_and_storage_key_are_unique(
    migrated_database: tuple[Config, Engine],
    duplicate_field: str,
) -> None:
    config, engine = migrated_database
    _upgrade(config)
    with engine.begin() as connection:
        organization_id = _insert_organization(connection, "unique-file")
        user_id = _insert_user(connection, organization_id, "unique@example.com")
        original = _file_values(organization_id, user_id)
        _insert_file(connection, original)

    duplicate = _file_values(
        organization_id,
        user_id,
        **{duplicate_field: original[duplicate_field]},
    )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert_file(connection, duplicate)


def test_downgrade_removes_file_schema(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    _upgrade(config)

    command.downgrade(config, PREVIOUS_HEAD)

    assert "files" not in inspect(engine).get_table_names()


def test_deleting_status_migration_upgrade_and_downgrade(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, "20260925_0010")
    with engine.begin() as connection:
        organization_id = _insert_organization(connection, "deleting-status")
        user_id = _insert_user(connection, organization_id, "deleting@example.com")

    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert_file(
            connection,
            _file_values(
                organization_id,
                user_id,
                storage_status="deleting",
            ),
        )

    command.upgrade(config, "head")
    with engine.begin() as connection:
        deleting_id = _insert_file(
            connection,
            _file_values(
                organization_id,
                user_id,
                storage_status="deleting",
            ),
        )
        assert deleting_id is not None

    command.downgrade(config, "20260925_0010")

    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM files WHERE storage_status = 'deleting'")
            )
            == 0
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert_file(
            connection,
            _file_values(
                organization_id,
                user_id,
                storage_status="deleting",
            ),
        )
