"""Add narrowly scoped Document dispatch leases.

Revision ID: 20261005_0017
Revises: 20261005_0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261005_0017"
down_revision: str | None = "20261005_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_processing_requests",
        sa.Column("dispatch_lease_token", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "document_processing_requests",
        sa.Column("dispatch_lease_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "document_processing_requests",
        sa.Column(
            "dispatch_next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.add_column(
        "document_processing_requests",
        sa.Column(
            "dispatch_attempts", sa.Integer(), server_default="0", nullable=False
        ),
    )
    op.create_check_constraint(
        "ck_document_requests_attempts",
        "document_processing_requests",
        "dispatch_attempts >= 0",
    )
    op.create_check_constraint(
        "ck_document_requests_lease_pair",
        "document_processing_requests",
        "(dispatch_lease_token IS NULL) = (dispatch_lease_until IS NULL)",
    )
    op.drop_index(
        "ix_document_requests_pending", table_name="document_processing_requests"
    )
    op.create_index(
        "ix_document_requests_pending",
        "document_processing_requests",
        ["dispatch_next_attempt_at", "id"],
        postgresql_where=sa.text("dispatched_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_requests_pending", table_name="document_processing_requests"
    )
    op.create_index(
        "ix_document_requests_pending",
        "document_processing_requests",
        ["created_at", "id"],
        postgresql_where=sa.text("dispatched_at IS NULL"),
    )
    op.drop_constraint(
        "ck_document_requests_lease_pair", "document_processing_requests", type_="check"
    )
    op.drop_constraint(
        "ck_document_requests_attempts", "document_processing_requests", type_="check"
    )
    for column in (
        "dispatch_attempts",
        "dispatch_next_attempt_at",
        "dispatch_lease_until",
        "dispatch_lease_token",
    ):
        op.drop_column("document_processing_requests", column)
