from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from nexus.infrastructure.persistence.models import Document


def test_document_model_defines_tenant_safe_file_relationship() -> None:
    constraints = Document.__table__.constraints

    assert Document.__tablename__ == "documents"
    assert Document.__table__.c.id.primary_key is True
    assert any(
        isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_documents_source_file_organization_files"
        for constraint in constraints
    )
    assert any(
        isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_documents_public_id"
        for constraint in constraints
    )


def test_document_model_defines_lifecycle_constraints_and_active_index() -> None:
    constraint_names = {
        constraint.name
        for constraint in Document.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    indexes = {index.name: index for index in Document.__table__.indexes}

    assert {
        "ck_documents_extractor_version",
        "ck_documents_failure_code_format",
        "ck_documents_failure_message_nonblank",
        "ck_documents_lifecycle_metadata",
        "ck_documents_processing_version",
        "ck_documents_public_id_nonzero",
        "ck_documents_status",
        "ck_documents_timestamp_order",
    } == constraint_names
    active_index = indexes["uq_documents_active_source_file_id"]
    assert active_index.unique is True
    assert active_index.columns.keys() == ["source_file_id"]
    assert active_index.dialect_options["postgresql"]["where"] is not None
