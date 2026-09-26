"""Add deleting File lifecycle status.

Revision ID: 20260926_0011
Revises: 20260925_0010
Create Date: 2026-09-26 19:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260926_0011"
down_revision: str | None = "20260925_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_files_storage_status", "files", type_="check")
    op.create_check_constraint(
        "ck_files_storage_status",
        "files",
        "storage_status IN ('pending', 'available', 'failed', 'deleting')",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE files SET storage_status = 'failed' WHERE storage_status = 'deleting'"
    )
    op.drop_constraint("ck_files_storage_status", "files", type_="check")
    op.create_check_constraint(
        "ck_files_storage_status",
        "files",
        "storage_status IN ('pending', 'available', 'failed')",
    )
