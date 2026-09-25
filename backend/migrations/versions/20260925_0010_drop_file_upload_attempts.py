"""Remove pre-upload File persistence.

Revision ID: 20260925_0010
Revises: 20260925_0009
Create Date: 2026-09-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260925_0010"
down_revision: str | None = "20260925_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("file_upload_attempts")


def downgrade() -> None:
    op.create_table(
        "file_upload_attempts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("file_id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("declared_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "grant_expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["file_id", "organization_id"],
            ["files.id", "files.organization_id"],
            name="fk_file_upload_attempts_file_organization_files",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "declared_size_bytes >= 0",
            name="ck_file_upload_attempts_declared_size_bytes_nonnegative",
        ),
        sa.CheckConstraint(
            "grant_expires_at > created_at",
            name="ck_file_upload_attempts_grant_expires_after_created_at",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_file_upload_attempts"),
    )
    op.create_index(
        "ix_file_upload_attempts_organization_file_created_at",
        "file_upload_attempts",
        ["organization_id", "file_id", "created_at"],
    )
