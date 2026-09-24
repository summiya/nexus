from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from nexus.infrastructure.persistence.models import File


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
