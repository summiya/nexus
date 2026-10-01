from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from nexus.documents.ports import DocumentPersistenceError
from nexus.infrastructure.persistence import _document_queries as queries
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
    assert any(
        isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_documents_id_organization_id"
        and constraint.columns.keys() == ["id", "organization_id"]
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


def test_malformed_stored_snapshot_maps_to_safe_persistence_error() -> None:
    model = Document(
        public_id=uuid4(),
        organization_id=1,
        source_file_id=1,
        status="unknown",
        created_at=datetime(2026, 10, 1, 8, 0, tzinfo=UTC),
    )

    with pytest.raises(
        DocumentPersistenceError,
        match="^Document persistence failed$",
    ):
        queries._to_document(model, uuid4(), uuid4())
