"""Organization model-provider configuration persistence models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nexus.infrastructure.persistence.base import Base


class ModelProvider(Base):
    """One non-secret provider configuration owned by an organization."""

    __tablename__ = "model_providers"
    __table_args__ = (
        CheckConstraint(
            "provider_type IN ('openai', 'anthropic', 'azure_openai', "
            "'gemini', 'openai_compatible')",
            name="ck_model_providers_provider_type",
        ),
        CheckConstraint(
            "display_name ~ '\\S'",
            name="ck_model_providers_display_name_nonblank",
        ),
        CheckConstraint(
            "validation_status IN ('unvalidated', 'valid', "
            "'invalid_credentials', 'unreachable', "
            "'unsupported_configuration')",
            name="ck_model_providers_validation_status",
        ),
        CheckConstraint(
            "(validation_status = 'unvalidated' AND last_validated_at IS NULL) OR "
            "(validation_status <> 'unvalidated' AND last_validated_at IS NOT NULL)",
            name="ck_model_providers_validation_timestamp",
        ),
        CheckConstraint(
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
        UniqueConstraint("public_id", name="uq_model_providers_public_id"),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_model_providers_organization_id_id",
        ),
        UniqueConstraint(
            "organization_id",
            "display_name",
            name="uq_model_providers_organization_id_display_name",
        ),
        Index(
            "uq_model_providers_credential_reference_not_null",
            "credential_reference",
            unique=True,
            postgresql_where=text("credential_reference IS NOT NULL"),
        ),
        Index(
            "ix_model_providers_organization_id_public_id",
            "organization_id",
            "public_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "organizations.id",
            name="fk_model_providers_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    settings_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    credential_reference: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    validation_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="unvalidated",
        server_default=text("'unvalidated'"),
    )
    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ConfiguredModel(Base):
    """One organization model exposed through a configured provider."""

    __tablename__ = "configured_models"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "provider_id"],
            ["model_providers.organization_id", "model_providers.id"],
            name="fk_configured_models_organization_provider",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "provider_model_name ~ '\\S'",
            name="ck_configured_models_provider_model_name_nonblank",
        ),
        CheckConstraint(
            "display_name ~ '\\S'",
            name="ck_configured_models_display_name_nonblank",
        ),
        CheckConstraint(
            "model_type IN ('chat', 'embedding', 'reranker')",
            name="ck_configured_models_model_type",
        ),
        CheckConstraint(
            "capabilities <@ ARRAY['streaming', 'tools', 'vision', "
            "'structured_output']::varchar[] "
            "AND array_position(capabilities, NULL) IS NULL",
            name="ck_configured_models_capabilities",
        ),
        CheckConstraint(
            "model_type = 'chat' OR cardinality(capabilities) = 0",
            name="ck_configured_models_capabilities_model_type",
        ),
        CheckConstraint(
            "(model_type = 'embedding' AND embedding_dimension IS NOT NULL "
            "AND embedding_dimension > 0) OR "
            "(model_type IN ('chat', 'reranker') AND embedding_dimension IS NULL)",
            name="ck_configured_models_embedding_dimension",
        ),
        UniqueConstraint("public_id", name="uq_configured_models_public_id"),
        UniqueConstraint(
            "organization_id",
            "model_type",
            "id",
            name="uq_configured_models_organization_type_id",
        ),
        UniqueConstraint(
            "organization_id",
            "provider_id",
            "model_type",
            "provider_model_name",
            name="uq_configured_models_provider_model_identity",
        ),
        Index(
            "ix_configured_models_organization_id_public_id",
            "organization_id",
            "public_id",
        ),
        Index(
            "ix_configured_models_organization_id_provider_id",
            "organization_id",
            "provider_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    provider_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    provider_model_name: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    model_type: Mapped[str] = mapped_column(String(32), nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)),
        nullable=False,
        default=list,
        server_default=text("'{}'::varchar[]"),
    )
    embedding_dimension: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class OrganizationModelDefault(Base):
    """One configured default for an organization and model type."""

    __tablename__ = "organization_model_defaults"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "model_type", "configured_model_id"],
            [
                "configured_models.organization_id",
                "configured_models.model_type",
                "configured_models.id",
            ],
            name="fk_organization_model_defaults_tenant_model",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "model_type IN ('chat', 'embedding', 'reranker')",
            name="ck_organization_model_defaults_model_type",
        ),
    )

    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "organizations.id",
            name="fk_organization_model_defaults_organization",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    model_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    configured_model_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
