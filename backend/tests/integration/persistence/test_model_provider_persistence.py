from __future__ import annotations

import asyncio
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from nexus.infrastructure.persistence import _model_provider_queries as queries
from nexus.infrastructure.persistence.model_provider import (
    SqlAlchemyModelProviderPersistence,
)
from nexus.infrastructure.persistence.models.model_provider import (
    ConfiguredModel as ConfiguredModelRecord,
)
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.model_providers.domain import (
    ConfiguredModel,
    ConfiguredModelId,
    ConfiguredProvider,
    CredentialReference,
    ModelCapability,
    ModelProviderConfigurationError,
    ModelType,
    OpenAISettings,
    OrganizationProviderId,
    ProviderType,
)
from nexus.model_providers.ports import (
    ModelProviderConflictError,
    ModelProviderPersistenceError,
    ModelProviderReferenceError,
)


@pytest.fixture
def migrated_engine(migrated_database: tuple[Config, Engine]) -> Engine:
    config, engine = migrated_database
    command.upgrade(config, "head")
    return engine


def _seed_organization(engine: Engine) -> UUID:
    public_id = uuid4()
    with Session(engine) as session:
        session.add(
            Organization(
                public_id=public_id,
                name="Model Organization",
                slug=f"models-{uuid4().hex[:12]}",
                status="active",
            )
        )
        session.commit()
    return public_id


def _provider(
    organization_public_id: UUID,
    *,
    credential_reference: CredentialReference | None = None,
) -> ConfiguredProvider:
    return ConfiguredProvider(
        organization_public_id=organization_public_id,
        provider_id=OrganizationProviderId(uuid4()),
        provider_type=ProviderType.OPENAI,
        display_name=f"OpenAI {uuid4().hex[:8]}",
        settings=OpenAISettings(),
        enabled=True,
        credential_reference=credential_reference,
    )


def _chat_model(
    organization_public_id: UUID,
    provider_id: OrganizationProviderId,
) -> ConfiguredModel:
    return ConfiguredModel(
        organization_public_id=organization_public_id,
        model_id=ConfiguredModelId(uuid4()),
        provider_id=provider_id,
        provider_model_name=f"gpt-{uuid4().hex[:8]}",
        display_name="Primary Chat",
        model_type=ModelType.CHAT,
        capabilities=frozenset({ModelCapability.TOOLS, ModelCapability.STREAMING}),
        enabled=True,
    )


def _persistence(
    factory: async_sessionmaker[AsyncSession],
) -> SqlAlchemyModelProviderPersistence:
    return SqlAlchemyModelProviderPersistence(factory)


async def _create_complete_configuration(
    persistence: SqlAlchemyModelProviderPersistence,
    organization_public_id: UUID,
) -> tuple[ConfiguredProvider, ConfiguredModel]:
    provider = _provider(organization_public_id)
    model = _chat_model(organization_public_id, provider.provider_id)
    await persistence.create_provider(provider)
    await persistence.create_model(model)
    await persistence.set_default(
        organization_public_id=organization_public_id,
        model_type=ModelType.CHAT,
        model_id=model.model_id,
    )
    return provider, model


def test_round_trip_returns_valid_domain_aggregate_and_sorted_capabilities(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id = _seed_organization(migrated_engine)
    persistence = _persistence(persistence_async_session_factory)
    provider, model = asyncio.run(
        _create_complete_configuration(persistence, organization_public_id)
    )

    configuration = asyncio.run(
        persistence.load_configuration(organization_public_id=organization_public_id)
    )

    assert configuration is not None
    assert configuration.providers == (provider,)
    assert configuration.models == (model,)
    assert configuration.defaults.chat == model.model_id
    assert not hasattr(configuration.providers[0], "id")
    with Session(migrated_engine) as session:
        record = session.scalar(
            select(ConfiguredModelRecord).where(
                ConfiguredModelRecord.public_id == model.model_id.value
            )
        )
        assert record is not None
        assert record.capabilities == ["streaming", "tools"]


def test_unknown_and_wrong_tenant_references_are_hidden(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first_organization_id = _seed_organization(migrated_engine)
    second_organization_id = _seed_organization(migrated_engine)
    persistence = _persistence(persistence_async_session_factory)
    provider = _provider(first_organization_id)
    asyncio.run(persistence.create_provider(provider))

    assert (
        asyncio.run(persistence.load_configuration(organization_public_id=uuid4()))
        is None
    )
    with pytest.raises(ModelProviderReferenceError):
        asyncio.run(
            persistence.delete_provider(
                organization_public_id=second_organization_id,
                provider_id=provider.provider_id,
            )
        )
    second_configuration = asyncio.run(
        persistence.load_configuration(organization_public_id=second_organization_id)
    )
    assert second_configuration is not None
    assert second_configuration.providers == ()
    assert second_configuration.models == ()


def test_credential_reference_is_unique_across_providers(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id = _seed_organization(migrated_engine)
    credential_reference = CredentialReference(uuid4())
    persistence = _persistence(persistence_async_session_factory)
    asyncio.run(
        persistence.create_provider(
            _provider(
                organization_public_id,
                credential_reference=credential_reference,
            )
        )
    )

    with pytest.raises(ModelProviderConflictError):
        asyncio.run(
            persistence.create_provider(
                _provider(
                    organization_public_id,
                    credential_reference=credential_reference,
                )
            )
        )


def test_duplicate_provider_display_name_maps_to_conflict(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id = _seed_organization(migrated_engine)
    persistence = _persistence(persistence_async_session_factory)
    provider = _provider(organization_public_id)
    asyncio.run(persistence.create_provider(provider))

    with pytest.raises(ModelProviderConflictError):
        asyncio.run(
            persistence.create_provider(
                replace(
                    _provider(organization_public_id),
                    display_name=provider.display_name,
                )
            )
        )


def test_unexpected_integrity_error_remains_persistence_failure(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_public_id = _seed_organization(migrated_engine)
    persistence = _persistence(persistence_async_session_factory)

    async def fail_insert(*args: object, **kwargs: object) -> None:
        raise IntegrityError("unexpected", {}, RuntimeError("unexpected"))

    monkeypatch.setattr(queries, "insert_provider", fail_insert)

    with pytest.raises(ModelProviderPersistenceError):
        asyncio.run(persistence.create_provider(_provider(organization_public_id)))


def test_invalid_stored_aggregate_is_rejected_on_load(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id = _seed_organization(migrated_engine)
    with migrated_engine.begin() as connection:
        organization_id = connection.scalar(
            select(Organization.id).where(
                Organization.public_id == organization_public_id
            )
        )
        provider_id = connection.scalar(
            text(
                """
                INSERT INTO model_providers (
                    public_id, organization_id, provider_type, display_name,
                    settings_json, enabled
                ) VALUES (
                    :public_id, :organization_id, 'openai', 'Disabled',
                    '{}'::jsonb, false
                ) RETURNING id
                """
            ),
            {"public_id": uuid4(), "organization_id": organization_id},
        )
        model_id = connection.scalar(
            text(
                """
                INSERT INTO configured_models (
                    public_id, organization_id, provider_id,
                    provider_model_name, display_name, model_type,
                    capabilities, enabled
                ) VALUES (
                    :public_id, :organization_id, :provider_id,
                    'gpt-test', 'Chat', 'chat', ARRAY['streaming'], true
                ) RETURNING id
                """
            ),
            {
                "public_id": uuid4(),
                "organization_id": organization_id,
                "provider_id": provider_id,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO organization_model_defaults (
                    organization_id, model_type, configured_model_id
                ) VALUES (:organization_id, 'chat', :model_id)
                """
            ),
            {"organization_id": organization_id, "model_id": model_id},
        )

    with pytest.raises(ModelProviderConfigurationError):
        asyncio.run(
            _persistence(persistence_async_session_factory).load_configuration(
                organization_public_id=organization_public_id
            )
        )


def test_loading_configuration_uses_bounded_query_count(
    migrated_engine: Engine,
    persistence_async_engine: AsyncEngine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id = _seed_organization(migrated_engine)
    persistence = _persistence(persistence_async_session_factory)
    for _ in range(4):
        provider = _provider(organization_public_id)
        asyncio.run(persistence.create_provider(provider))
        asyncio.run(
            persistence.create_model(
                _chat_model(organization_public_id, provider.provider_id)
            )
        )

    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(
        persistence_async_engine.sync_engine,
        "before_cursor_execute",
        record_statement,
    )
    try:
        configuration = asyncio.run(
            persistence.load_configuration(
                organization_public_id=organization_public_id
            )
        )
    finally:
        event.remove(
            persistence_async_engine.sync_engine,
            "before_cursor_execute",
            record_statement,
        )

    assert configuration is not None
    assert len(configuration.providers) == 4
    assert len(configuration.models) == 4
    assert len(statements) == 4


@pytest.mark.parametrize("target", ["model", "provider", "streaming"])
def test_sequential_updates_cannot_invalidate_the_default_aggregate(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
    target: str,
) -> None:
    organization_public_id = _seed_organization(migrated_engine)
    persistence = _persistence(persistence_async_session_factory)
    provider, model = asyncio.run(
        _create_complete_configuration(persistence, organization_public_id)
    )

    if target == "model":
        operation = persistence.update_model(replace(model, enabled=False))
    elif target == "provider":
        operation = persistence.update_provider(replace(provider, enabled=False))
    else:
        operation = persistence.update_model(
            replace(model, capabilities=frozenset({ModelCapability.TOOLS}))
        )

    with pytest.raises(ModelProviderConfigurationError):
        asyncio.run(operation)

    configuration = asyncio.run(
        persistence.load_configuration(organization_public_id=organization_public_id)
    )
    assert configuration is not None
    assert configuration.defaults.chat == model.model_id
    assert configuration.providers[0].enabled is True
    assert configuration.models[0].enabled is True
    assert ModelCapability.STREAMING in configuration.models[0].capabilities


def test_concurrent_mutations_serialize_and_preserve_a_valid_aggregate(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id = _seed_organization(migrated_engine)
    persistence = _persistence(persistence_async_session_factory)
    provider = _provider(organization_public_id)
    model = _chat_model(organization_public_id, provider.provider_id)
    asyncio.run(persistence.create_provider(provider))
    asyncio.run(persistence.create_model(model))

    async def race() -> tuple[object, object]:
        results = await asyncio.gather(
            persistence.set_default(
                organization_public_id=organization_public_id,
                model_type=ModelType.CHAT,
                model_id=model.model_id,
            ),
            persistence.update_model(replace(model, enabled=False)),
            return_exceptions=True,
        )
        return results[0], results[1]

    results = asyncio.run(race())

    assert sum(result is None for result in results) == 1
    assert (
        sum(isinstance(result, ModelProviderConfigurationError) for result in results)
        == 1
    )
    configuration = asyncio.run(
        persistence.load_configuration(organization_public_id=organization_public_id)
    )
    assert configuration is not None
    if configuration.defaults.chat is None:
        assert configuration.models[0].enabled is False
    else:
        assert configuration.defaults.chat == model.model_id
        assert configuration.models[0].enabled is True
