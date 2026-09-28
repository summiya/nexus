"""Private SQLAlchemy queries for model-provider configuration persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.infrastructure.persistence.models.model_provider import (
    ConfiguredModel as ConfiguredModelRecord,
)
from nexus.infrastructure.persistence.models.model_provider import (
    ModelProvider as ModelProviderRecord,
)
from nexus.infrastructure.persistence.models.model_provider import (
    OrganizationModelDefault,
)
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.model_providers.domain import (
    ConfiguredModel,
    ConfiguredModelId,
    ConfiguredProvider,
    CredentialReference,
    DefaultModelSelection,
    ModelCapability,
    ModelType,
    OrganizationModelProviderConfiguration,
    OrganizationProviderId,
    ProviderType,
    provider_settings_from_mapping,
    provider_settings_to_mapping,
)


async def lock_organization(
    session: AsyncSession,
    *,
    organization_public_id: UUID,
) -> int | None:
    """Serialize configuration mutations for one organization."""
    return (
        await session.execute(
            select(Organization.id)
            .where(Organization.public_id == organization_public_id)
            .with_for_update()
        )
    ).scalar_one_or_none()


async def organization_id(
    session: AsyncSession,
    *,
    organization_public_id: UUID,
) -> int | None:
    return (
        await session.execute(
            select(Organization.id).where(
                Organization.public_id == organization_public_id
            )
        )
    ).scalar_one_or_none()


async def load_configuration(
    session: AsyncSession,
    *,
    organization_public_id: UUID,
    organization_id: int,
) -> OrganizationModelProviderConfiguration:
    provider_records = (
        await session.scalars(
            select(ModelProviderRecord)
            .where(ModelProviderRecord.organization_id == organization_id)
            .order_by(ModelProviderRecord.id)
        )
    ).all()
    model_records = (
        await session.scalars(
            select(ConfiguredModelRecord)
            .where(ConfiguredModelRecord.organization_id == organization_id)
            .order_by(ConfiguredModelRecord.id)
        )
    ).all()
    default_records = (
        await session.scalars(
            select(OrganizationModelDefault)
            .where(OrganizationModelDefault.organization_id == organization_id)
            .order_by(OrganizationModelDefault.model_type)
        )
    ).all()

    providers = tuple(
        _to_provider(record, organization_public_id) for record in provider_records
    )
    provider_ids = {
        record.id: OrganizationProviderId(record.public_id)
        for record in provider_records
    }
    models = tuple(
        _to_model(record, organization_public_id, provider_ids[record.provider_id])
        for record in model_records
    )
    model_ids = {
        record.id: ConfiguredModelId(record.public_id) for record in model_records
    }
    defaults_by_type = {
        ModelType(record.model_type): model_ids[record.configured_model_id]
        for record in default_records
    }
    return OrganizationModelProviderConfiguration(
        organization_public_id=organization_public_id,
        providers=providers,
        models=models,
        defaults=DefaultModelSelection(
            chat=defaults_by_type.get(ModelType.CHAT),
            embedding=defaults_by_type.get(ModelType.EMBEDDING),
            reranker=defaults_by_type.get(ModelType.RERANKER),
        ),
    )


async def insert_provider(
    session: AsyncSession,
    *,
    organization_id: int,
    provider: ConfiguredProvider,
) -> None:
    session.add(
        ModelProviderRecord(
            public_id=provider.provider_id.value,
            organization_id=organization_id,
            provider_type=provider.provider_type.value,
            display_name=provider.display_name,
            settings_json=provider_settings_to_mapping(provider.settings),
            credential_reference=_credential_value(provider.credential_reference),
            enabled=provider.enabled,
        )
    )
    await session.flush()


async def update_provider(
    session: AsyncSession,
    *,
    organization_id: int,
    provider: ConfiguredProvider,
) -> bool:
    record = await _provider_record(
        session,
        organization_id=organization_id,
        provider_id=provider.provider_id,
    )
    if record is None:
        return False
    record.provider_type = provider.provider_type.value
    record.display_name = provider.display_name
    record.settings_json = provider_settings_to_mapping(provider.settings)
    record.credential_reference = _credential_value(provider.credential_reference)
    record.enabled = provider.enabled
    await session.flush()
    return True


async def delete_provider(
    session: AsyncSession,
    *,
    organization_id: int,
    provider_id: OrganizationProviderId,
) -> bool:
    record = await _provider_record(
        session,
        organization_id=organization_id,
        provider_id=provider_id,
    )
    if record is None:
        return False
    await session.delete(record)
    await session.flush()
    return True


async def insert_model(
    session: AsyncSession,
    *,
    organization_id: int,
    model: ConfiguredModel,
) -> bool:
    provider_record = await _provider_record(
        session,
        organization_id=organization_id,
        provider_id=model.provider_id,
    )
    if provider_record is None:
        return False
    session.add(
        ConfiguredModelRecord(
            public_id=model.model_id.value,
            organization_id=organization_id,
            provider_id=provider_record.id,
            provider_model_name=model.provider_model_name,
            display_name=model.display_name,
            model_type=model.model_type.value,
            capabilities=_sorted_capabilities(model),
            embedding_dimension=model.embedding_dimension,
            enabled=model.enabled,
        )
    )
    await session.flush()
    return True


async def update_model(
    session: AsyncSession,
    *,
    organization_id: int,
    model: ConfiguredModel,
) -> bool:
    record = await _model_record(
        session,
        organization_id=organization_id,
        model_id=model.model_id,
    )
    provider_record = await _provider_record(
        session,
        organization_id=organization_id,
        provider_id=model.provider_id,
    )
    if record is None or provider_record is None:
        return False
    record.provider_id = provider_record.id
    record.provider_model_name = model.provider_model_name
    record.display_name = model.display_name
    record.model_type = model.model_type.value
    record.capabilities = _sorted_capabilities(model)
    record.embedding_dimension = model.embedding_dimension
    record.enabled = model.enabled
    await session.flush()
    return True


async def delete_model(
    session: AsyncSession,
    *,
    organization_id: int,
    model_id: ConfiguredModelId,
) -> bool:
    record = await _model_record(
        session,
        organization_id=organization_id,
        model_id=model_id,
    )
    if record is None:
        return False
    await session.delete(record)
    await session.flush()
    return True


async def set_default(
    session: AsyncSession,
    *,
    organization_id: int,
    model_type: ModelType,
    model_id: ConfiguredModelId | None,
) -> bool:
    if model_id is None:
        await session.execute(
            delete(OrganizationModelDefault).where(
                OrganizationModelDefault.organization_id == organization_id,
                OrganizationModelDefault.model_type == model_type.value,
            )
        )
        return True

    record = await _model_record(
        session,
        organization_id=organization_id,
        model_id=model_id,
    )
    if record is None:
        return False
    statement = insert(OrganizationModelDefault).values(
        organization_id=organization_id,
        model_type=model_type.value,
        configured_model_id=record.id,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["organization_id", "model_type"],
            set_={
                "configured_model_id": record.id,
                "updated_at": func.now(),
            },
        )
    )
    return True


async def _provider_record(
    session: AsyncSession,
    *,
    organization_id: int,
    provider_id: OrganizationProviderId,
) -> ModelProviderRecord | None:
    return (
        await session.scalars(
            select(ModelProviderRecord).where(
                ModelProviderRecord.organization_id == organization_id,
                ModelProviderRecord.public_id == provider_id.value,
            )
        )
    ).one_or_none()


async def _model_record(
    session: AsyncSession,
    *,
    organization_id: int,
    model_id: ConfiguredModelId,
) -> ConfiguredModelRecord | None:
    return (
        await session.scalars(
            select(ConfiguredModelRecord).where(
                ConfiguredModelRecord.organization_id == organization_id,
                ConfiguredModelRecord.public_id == model_id.value,
            )
        )
    ).one_or_none()


def _to_provider(
    record: ModelProviderRecord,
    organization_public_id: UUID,
) -> ConfiguredProvider:
    provider_type = ProviderType(record.provider_type)
    return ConfiguredProvider(
        organization_public_id=organization_public_id,
        provider_id=OrganizationProviderId(record.public_id),
        provider_type=provider_type,
        display_name=record.display_name,
        settings=provider_settings_from_mapping(provider_type, record.settings_json),
        credential_reference=(
            CredentialReference(record.credential_reference)
            if record.credential_reference is not None
            else None
        ),
        enabled=record.enabled,
    )


def _to_model(
    record: ConfiguredModelRecord,
    organization_public_id: UUID,
    provider_id: OrganizationProviderId,
) -> ConfiguredModel:
    return ConfiguredModel(
        organization_public_id=organization_public_id,
        model_id=ConfiguredModelId(record.public_id),
        provider_id=provider_id,
        provider_model_name=record.provider_model_name,
        display_name=record.display_name,
        model_type=ModelType(record.model_type),
        capabilities=frozenset(ModelCapability(value) for value in record.capabilities),
        embedding_dimension=record.embedding_dimension,
        enabled=record.enabled,
    )


def _credential_value(reference: CredentialReference | None) -> UUID | None:
    return reference.value if reference is not None else None


def _sorted_capabilities(model: ConfiguredModel) -> list[str]:
    return sorted({capability.value for capability in model.capabilities})
