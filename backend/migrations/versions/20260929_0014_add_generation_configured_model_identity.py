"""Add configured-model identity to Conversation generations.

Revision ID: 20260929_0014
Revises: 20260929_0013
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260929_0014"
down_revision: str | None = "20260929_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generations",
        sa.Column("configured_model_public_id", sa.Uuid(), nullable=True),
    )
    op.alter_column("generations", "model", existing_type=sa.Text(), nullable=True)
    op.drop_constraint(
        "ck_generations_model_nonblank",
        "generations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_generations_model_identity",
        "generations",
        "(model IS NOT NULL AND btrim(model) <> '' "
        "AND configured_model_public_id IS NULL) OR "
        "(model IS NULL AND configured_model_public_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_generations_model_identity",
        "generations",
        type_="check",
    )
    op.execute(
        "UPDATE generations SET model = configured_model_public_id::text "
        "WHERE model IS NULL"
    )
    op.alter_column("generations", "model", existing_type=sa.Text(), nullable=False)
    op.create_check_constraint(
        "ck_generations_model_nonblank",
        "generations",
        "btrim(model) <> ''",
    )
    op.drop_column("generations", "configured_model_public_id")
