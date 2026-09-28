"""Create organization model-provider configuration.

Revision ID: 20260928_0012
Revises: 20260926_0011
Create Date: 2026-09-28 12:00:00.000000
"""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260928_0012"
down_revision: str | None = "20260926_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERMISSIONS = (
    ("model_providers.read", "View model provider configuration"),
    ("model_providers.manage", "Manage model provider configuration"),
)


def upgrade() -> None:
    op.create_table(
        "model_providers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider_type", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column(
            "settings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("credential_reference", sa.Uuid(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
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
        sa.CheckConstraint(
            "provider_type IN ('openai', 'anthropic', 'azure_openai', "
            "'gemini', 'openai_compatible')",
            name="ck_model_providers_provider_type",
        ),
        sa.CheckConstraint(
            "display_name ~ '\\S'",
            name="ck_model_providers_display_name_nonblank",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(settings_json) = 'object' AND ("
            "(provider_type IN ('openai', 'anthropic', 'gemini') "
            "AND settings_json = '{}'::jsonb) OR "
            "(provider_type = 'azure_openai' "
            "AND settings_json ?& ARRAY['endpoint', 'api_version'] "
            "AND settings_json - ARRAY['endpoint', 'api_version'] = '{}'::jsonb "
            "AND jsonb_typeof(settings_json->'endpoint') = 'string' "
            "AND jsonb_typeof(settings_json->'api_version') = 'string') OR "
            "(provider_type = 'openai_compatible' "
            "AND settings_json ? 'base_url' "
            "AND settings_json - 'base_url' = '{}'::jsonb "
            "AND jsonb_typeof(settings_json->'base_url') = 'string'))",
            name="ck_model_providers_settings_shape",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_model_providers_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_providers"),
        sa.UniqueConstraint("public_id", name="uq_model_providers_public_id"),
        sa.UniqueConstraint(
            "organization_id",
            "id",
            name="uq_model_providers_organization_id_id",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "display_name",
            name="uq_model_providers_organization_id_display_name",
        ),
    )
    op.create_index(
        "uq_model_providers_credential_reference_not_null",
        "model_providers",
        ["credential_reference"],
        unique=True,
        postgresql_where=sa.text("credential_reference IS NOT NULL"),
    )
    op.create_index(
        "ix_model_providers_organization_id_public_id",
        "model_providers",
        ["organization_id", "public_id"],
    )

    op.create_table(
        "configured_models",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("provider_id", sa.BigInteger(), nullable=False),
        sa.Column("provider_model_name", sa.String(length=256), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("model_type", sa.String(length=32), nullable=False),
        sa.Column(
            "capabilities",
            postgresql.ARRAY(sa.String(length=32)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column("embedding_dimension", sa.BigInteger(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
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
        sa.CheckConstraint(
            "provider_model_name ~ '\\S'",
            name="ck_configured_models_provider_model_name_nonblank",
        ),
        sa.CheckConstraint(
            "display_name ~ '\\S'",
            name="ck_configured_models_display_name_nonblank",
        ),
        sa.CheckConstraint(
            "model_type IN ('chat', 'embedding', 'reranker')",
            name="ck_configured_models_model_type",
        ),
        sa.CheckConstraint(
            "capabilities <@ ARRAY['streaming', 'tools', 'vision', "
            "'structured_output']::varchar[] "
            "AND array_position(capabilities, NULL) IS NULL",
            name="ck_configured_models_capabilities",
        ),
        sa.CheckConstraint(
            "model_type = 'chat' OR cardinality(capabilities) = 0",
            name="ck_configured_models_capabilities_model_type",
        ),
        sa.CheckConstraint(
            "(model_type = 'embedding' AND embedding_dimension IS NOT NULL "
            "AND embedding_dimension > 0) OR "
            "(model_type IN ('chat', 'reranker') AND embedding_dimension IS NULL)",
            name="ck_configured_models_embedding_dimension",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "provider_id"],
            ["model_providers.organization_id", "model_providers.id"],
            name="fk_configured_models_organization_provider",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_configured_models"),
        sa.UniqueConstraint("public_id", name="uq_configured_models_public_id"),
        sa.UniqueConstraint(
            "organization_id",
            "model_type",
            "id",
            name="uq_configured_models_organization_type_id",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "provider_id",
            "model_type",
            "provider_model_name",
            name="uq_configured_models_provider_model_identity",
        ),
    )
    op.create_index(
        "ix_configured_models_organization_id_public_id",
        "configured_models",
        ["organization_id", "public_id"],
    )
    op.create_index(
        "ix_configured_models_organization_id_provider_id",
        "configured_models",
        ["organization_id", "provider_id"],
    )

    op.create_table(
        "organization_model_defaults",
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("model_type", sa.String(length=32), nullable=False),
        sa.Column("configured_model_id", sa.BigInteger(), nullable=False),
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
        sa.CheckConstraint(
            "model_type IN ('chat', 'embedding', 'reranker')",
            name="ck_organization_model_defaults_model_type",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_organization_model_defaults_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "model_type", "configured_model_id"],
            [
                "configured_models.organization_id",
                "configured_models.model_type",
                "configured_models.id",
            ],
            name="fk_organization_model_defaults_tenant_model",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "organization_id",
            "model_type",
            name="pk_organization_model_defaults",
        ),
    )

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
                "public_id": uuid5(NAMESPACE_URL, f"nexus:permission:{key}"),
                "key": key,
                "description": description,
            }
            for key, description in _PERMISSIONS
        ],
    )
    permission_keys = tuple(key for key, _ in _PERMISSIONS)
    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT roles.id, permissions.id
            FROM roles
            CROSS JOIN permissions
            WHERE roles.name = 'Administrator'
              AND roles.is_system = true
              AND permissions.key IN :permission_keys
            ON CONFLICT DO NOTHING
            """
        ).bindparams(sa.bindparam("permission_keys", expanding=True)),
        {"permission_keys": permission_keys},
    )


def downgrade() -> None:
    permission_keys = tuple(key for key, _ in _PERMISSIONS)
    op.get_bind().execute(
        sa.text(
            """
            DELETE FROM role_permissions
            WHERE permission_id IN (
                SELECT id FROM permissions WHERE key IN :permission_keys
            )
            """
        ).bindparams(sa.bindparam("permission_keys", expanding=True)),
        {"permission_keys": permission_keys},
    )
    op.get_bind().execute(
        sa.text("DELETE FROM permissions WHERE key IN :permission_keys").bindparams(
            sa.bindparam("permission_keys", expanding=True)
        ),
        {"permission_keys": permission_keys},
    )

    op.drop_table("organization_model_defaults")
    op.drop_index(
        "ix_configured_models_organization_id_provider_id",
        table_name="configured_models",
    )
    op.drop_index(
        "ix_configured_models_organization_id_public_id",
        table_name="configured_models",
    )
    op.drop_table("configured_models")
    op.drop_index(
        "ix_model_providers_organization_id_public_id",
        table_name="model_providers",
    )
    op.drop_index(
        "uq_model_providers_credential_reference_not_null",
        table_name="model_providers",
    )
    op.drop_table("model_providers")
