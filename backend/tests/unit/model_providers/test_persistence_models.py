from __future__ import annotations

from nexus.infrastructure.persistence.models.model_provider import (
    ConfiguredModel,
    ModelProvider,
    OrganizationModelDefault,
)


def test_provider_model_schema_has_named_tenant_and_conflict_constraints() -> None:
    provider_names = {
        constraint.name for constraint in ModelProvider.__table__.constraints
    } | {index.name for index in ModelProvider.__table__.indexes}
    model_names = {
        constraint.name for constraint in ConfiguredModel.__table__.constraints
    } | {index.name for index in ConfiguredModel.__table__.indexes}
    default_names = {
        constraint.name for constraint in OrganizationModelDefault.__table__.constraints
    }

    assert "uq_model_providers_credential_reference_not_null" in provider_names
    assert "uq_model_providers_organization_id_display_name" in provider_names
    assert "ck_model_providers_validation_status" in provider_names
    assert "ck_model_providers_validation_timestamp" in provider_names
    assert "fk_configured_models_organization_provider" in model_names
    assert "uq_configured_models_provider_model_identity" in model_names
    assert "fk_organization_model_defaults_tenant_model" in default_names


def test_models_do_not_store_provider_secret_material() -> None:
    column_names = {
        *(column.name for column in ModelProvider.__table__.columns),
        *(column.name for column in ConfiguredModel.__table__.columns),
        *(column.name for column in OrganizationModelDefault.__table__.columns),
    }

    assert column_names.isdisjoint(
        {"api_key", "secret", "token", "credential", "credential_value"}
    )
    assert "credential_reference" in column_names
