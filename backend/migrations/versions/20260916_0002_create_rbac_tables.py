"""Create RBAC roles and permissions.

Revision ID: 20260916_0002
Revises: 20260916_0001
Create Date: 2026-09-16 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260916_0002"
down_revision: str | None = "20260916_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSIONS = (
    ("users.read", "View users in the organization"),
    ("users.manage", "Manage users in the organization"),
    ("organizations.read", "View organization settings"),
    ("organizations.manage", "Manage organization settings"),
    ("roles.read", "View roles"),
    ("roles.manage", "Manage roles and role permissions"),
    ("permissions.read", "View the permission catalog"),
    ("conversations.read", "View conversations"),
    ("conversations.create", "Create conversations"),
    ("conversations.delete", "Delete conversations"),
    ("files.read", "View files"),
    ("files.upload", "Upload files"),
    ("files.delete", "Delete files"),
)


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("is_system", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"],
            name="fk_roles_organization_id_organizations", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("organization_id", "name", name="uq_roles_organization_id_name"),
    )
    op.create_index("ix_roles_organization_id", "roles", ["organization_id"])
    op.create_index("ix_roles_public_id", "roles", ["public_id"], unique=True)

    op.create_table(
        "permissions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_permissions"),
    )
    op.create_index("ix_permissions_public_id", "permissions", ["public_id"], unique=True)
    op.create_index("ix_permissions_key", "permissions", ["key"], unique=True)

    permissions = sa.table(
        "permissions",
        sa.column("public_id", sa.Uuid()),
        sa.column("key", sa.String()),
        sa.column("description", sa.String()),
    )
    op.bulk_insert(
        permissions,
        [
            {
                "public_id": __import__("uuid").uuid5(
                    __import__("uuid").NAMESPACE_URL, f"nexus:permission:{key}"
                ),
                "key": key,
                "description": description,
            }
            for key, description in PERMISSIONS
        ],
    )

    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("permission_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["permission_id"], ["permissions.id"],
            name="fk_role_permissions_permission_id_permissions", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"],
            name="fk_role_permissions_role_id_roles", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name="pk_role_permissions"),
        sa.UniqueConstraint(
            "role_id", "permission_id", name="uq_role_permissions_role_id_permission_id"
        ),
    )


def downgrade() -> None:
    op.drop_table("role_permissions")
    op.drop_index("ix_permissions_key", table_name="permissions")
    op.drop_index("ix_permissions_public_id", table_name="permissions")
    op.drop_table("permissions")
    op.drop_index("ix_roles_public_id", table_name="roles")
    op.drop_index("ix_roles_organization_id", table_name="roles")
    op.drop_table("roles")
