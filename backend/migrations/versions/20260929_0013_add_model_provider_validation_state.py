"""Add current provider validation state.

Revision ID: 20260929_0013
Revises: 20260928_0012
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260929_0013"
down_revision: str | None = "20260928_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_providers",
        sa.Column(
            "validation_status",
            sa.String(length=32),
            nullable=False,
            server_default="unvalidated",
        ),
    )
    op.add_column(
        "model_providers",
        sa.Column(
            "last_validated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_model_providers_validation_status",
        "model_providers",
        "validation_status IN ('unvalidated', 'valid', 'invalid_credentials', "
        "'unreachable', 'unsupported_configuration')",
    )
    op.create_check_constraint(
        "ck_model_providers_validation_timestamp",
        "model_providers",
        "(validation_status = 'unvalidated' AND last_validated_at IS NULL) OR "
        "(validation_status <> 'unvalidated' AND last_validated_at IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_model_providers_validation_timestamp",
        "model_providers",
        type_="check",
    )
    op.drop_constraint(
        "ck_model_providers_validation_status",
        "model_providers",
        type_="check",
    )
    op.drop_column("model_providers", "last_validated_at")
    op.drop_column("model_providers", "validation_status")
