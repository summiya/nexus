"""Create tenant-safe user-role assignments.

Revision ID: 20260916_0003
Revises: 20260916_0002
Create Date: 2026-09-16 15:36:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260916_0003"
down_revision: str | None = "20260916_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_users_id_organization_id",
        "users",
        ["id", "organization_id"],
    )
    op.create_unique_constraint(
        "uq_roles_id_organization_id",
        "roles",
        ["id", "organization_id"],
    )

    op.create_table(
        "user_roles",
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_user_roles_user_organization_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id", "organization_id"],
            ["roles.id", "roles.organization_id"],
            name="fk_user_roles_role_organization_roles",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "role_id", name="pk_user_roles"),
    )
    op.create_index("ix_user_roles_organization_id", "user_roles", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_user_roles_organization_id", table_name="user_roles")
    op.drop_table("user_roles")
    op.drop_constraint("uq_roles_id_organization_id", "roles", type_="unique")
    op.drop_constraint("uq_users_id_organization_id", "users", type_="unique")
