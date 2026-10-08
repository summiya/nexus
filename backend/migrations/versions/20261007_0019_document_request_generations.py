"""Retain one processing request per Document generation.

Revision ID: 20261007_0019
Revises: 20261007_0018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261007_0019"
down_revision: str | None = "20261007_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_document_requests_initial_file",
        "document_processing_requests",
        type_="unique",
    )
    op.create_index(
        "ix_document_requests_source_file_id",
        "document_processing_requests",
        ["source_file_id", "id"],
    )


def downgrade() -> None:
    duplicates = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM document_processing_requests "
            "GROUP BY source_file_id HAVING count(*) > 1)"
        )
    )
    if duplicates:
        raise RuntimeError("Cannot downgrade retained Document generation history")
    op.drop_index("ix_document_requests_source_file_id", "document_processing_requests")
    op.create_unique_constraint(
        "uq_document_requests_initial_file",
        "document_processing_requests",
        ["source_file_id"],
    )
