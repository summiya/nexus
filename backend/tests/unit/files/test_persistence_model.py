from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from nexus.infrastructure.persistence.models import File, FileUploadAttempt


def test_file_model_defines_tenant_and_creator_integrity() -> None:
    constraints = File.__table__.constraints

    assert File.__tablename__ == "files"
    assert File.__table__.c.id.primary_key is True
    assert any(
        isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_files_organization_id_organizations"
        for constraint in constraints
    )
    assert any(
        isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_files_creator_organization_users"
        for constraint in constraints
    )
    assert any(
        isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_files_id_organization_id"
        for constraint in constraints
    )


def test_file_model_defines_storage_constraints() -> None:
    constraints = File.__table__.constraints
    constraint_names = {
        constraint.name
        for constraint in constraints
        if isinstance(constraint, (CheckConstraint, UniqueConstraint))
    }

    assert {
        "uq_files_public_id",
        "uq_files_storage_key",
        "ck_files_original_name_nonblank",
        "ck_files_mime_type_nonblank",
        "ck_files_storage_key_nonblank",
        "ck_files_size_bytes_nonnegative",
        "ck_files_storage_status",
        "ck_files_checksum_sha256_format",
        "ck_files_available_size",
    }.issubset(constraint_names)
    assert File.__table__.c.size_bytes.nullable is True
    assert File.__table__.c.checksum_sha256.nullable is True


def test_file_model_defines_cursor_ready_tenant_index() -> None:
    indexes = {index.name: index for index in File.__table__.indexes}

    assert indexes["ix_files_organization_created_at_public_id"].columns.keys() == [
        "organization_id",
        "created_at",
        "public_id",
    ]


def test_file_upload_attempt_model_defines_trusted_state_columns() -> None:
    columns = FileUploadAttempt.__table__.c

    assert FileUploadAttempt.__tablename__ == "file_upload_attempts"
    assert columns.id.primary_key is True
    assert columns.file_id.nullable is False
    assert columns.organization_id.nullable is False
    assert columns.declared_size_bytes.nullable is False
    assert columns.grant_expires_at.nullable is False
    assert columns.created_at.nullable is False
    assert set(columns.keys()) == {
        "id",
        "file_id",
        "organization_id",
        "declared_size_bytes",
        "grant_expires_at",
        "created_at",
    }


def test_file_upload_attempt_model_defines_tenant_safe_file_reference() -> None:
    constraints = FileUploadAttempt.__table__.constraints
    foreign_key = next(
        constraint
        for constraint in constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_file_upload_attempts_file_organization_files"
    )

    assert [element.parent.name for element in foreign_key.elements] == [
        "file_id",
        "organization_id",
    ]
    assert [element.target_fullname for element in foreign_key.elements] == [
        "files.id",
        "files.organization_id",
    ]
    assert foreign_key.ondelete == "CASCADE"


def test_file_upload_attempt_model_defines_checks_without_attempt_uniqueness() -> None:
    constraints = FileUploadAttempt.__table__.constraints
    check_names = {
        constraint.name
        for constraint in constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert check_names == {
        "ck_file_upload_attempts_declared_size_bytes_nonnegative",
        "ck_file_upload_attempts_grant_expires_after_created_at",
    }
    assert not any(isinstance(item, UniqueConstraint) for item in constraints)


def test_file_upload_attempt_model_defines_lookup_index() -> None:
    indexes = {index.name: index for index in FileUploadAttempt.__table__.indexes}

    assert set(indexes) == {
        "ix_file_upload_attempts_organization_file_created_at",
    }
    assert indexes[
        "ix_file_upload_attempts_organization_file_created_at"
    ].columns.keys() == ["organization_id", "file_id", "created_at"]
