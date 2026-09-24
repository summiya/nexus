"""Create File persistence table.

Revision ID: 20260924_0008
Revises: 20260922_0007
Create Date: 2026-09-24 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_0008"
down_revision: str | None = "20260922_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("storage_status", sa.String(length=32), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_files_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_files_creator_organization_users",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint(
            "original_name ~ '\\S'",
            name="ck_files_original_name_nonblank",
        ),
        sa.CheckConstraint(
            "mime_type ~ '\\S'",
            name="ck_files_mime_type_nonblank",
        ),
        sa.CheckConstraint(
            "storage_key ~ '\\S'",
            name="ck_files_storage_key_nonblank",
        ),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="ck_files_size_bytes_nonnegative",
        ),
        sa.CheckConstraint(
            "storage_status IN ('pending', 'available', 'failed')",
            name="ck_files_storage_status",
        ),
        sa.CheckConstraint(
            "checksum_sha256 IS NULL OR checksum_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_files_checksum_sha256_format",
        ),
        sa.CheckConstraint(
            "storage_status <> 'available' OR size_bytes IS NOT NULL",
            name="ck_files_available_size",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_files"),
        sa.UniqueConstraint("public_id", name="uq_files_public_id"),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_files_id_organization_id",
        ),
        sa.UniqueConstraint("storage_key", name="uq_files_storage_key"),
    )
    op.create_index(
        "ix_files_organization_created_at_public_id",
        "files",
        ["organization_id", "created_at", "public_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_files_organization_created_at_public_id",
        table_name="files",
    )
    op.drop_table("files")
