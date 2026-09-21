"""Enforce Conversation generation concurrency and request deduplication.

Revision ID: 20260922_0007
Revises: 20260916_0006
Create Date: 2026-09-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260922_0007"
down_revision: str | None = "20260916_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVE_GENERATION_INDEX = "uq_generations_one_running_per_conversation"
IDEMPOTENCY_INDEX = "uq_generations_conversation_idempotency_key"
RUNNING_STATUS = "running"


def upgrade() -> None:
    duplicate = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT organization_id, conversation_id
            FROM generations
            WHERE status = :running_status
            GROUP BY organization_id, conversation_id
            HAVING count(*) > 1
            LIMIT 1
            """
            ),
            {"running_status": RUNNING_STATUS},
        )
        .first()
    )
    if duplicate is not None:
        raise RuntimeError(
            "Cannot enforce one running Generation per Conversation while "
            "duplicate running Generations exist"
        )

    op.add_column(
        "generations",
        sa.Column("idempotency_key", sa.Uuid(), nullable=True),
    )
    op.create_index(
        ACTIVE_GENERATION_INDEX,
        "generations",
        ["organization_id", "conversation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        IDEMPOTENCY_INDEX,
        "generations",
        ["organization_id", "conversation_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(IDEMPOTENCY_INDEX, table_name="generations")
    op.drop_index(ACTIVE_GENERATION_INDEX, table_name="generations")
    op.drop_column("generations", "idempotency_key")
