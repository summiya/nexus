from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
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
from nexus.infrastructure.persistence.models.model_provider import (
    ModelProvider as ModelProviderRecord,
)
from nexus.infrastructure.persistence.models.model_provider import (
    OrganizationModelDefault,
)
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.model_providers.domain import (
    AnthropicSettings,
    AzureOpenAISettings,
    ConfiguredModel,
    ConfiguredModelId,
    ConfiguredProvider,
    CredentialReference,
    GeminiSettings,
    ModelCapability,
    ModelProviderConfigurationError,
    ModelType,
    OpenAICompatibleSettings,
    OpenAISettings,
    OrganizationProviderId,
    ProviderSettings,
    ProviderType,
    ProviderValidationStatus,
)
from nexus.model_providers.ports import (
    ModelProviderConflictError,
    ModelProviderDeleteRestrictedError,
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


@pytest.mark.parametrize(
    ("provider_type", "settings"),
    [
        (ProviderType.OPENAI, OpenAISettings()),
        (ProviderType.ANTHROPIC, AnthropicSettings()),
        (
            ProviderType.AZURE_OPENAI,
            AzureOpenAISettings(
                endpoint="https://models.example.com",
                api_version="2026-09-01",
            ),
        ),
        (ProviderType.GEMINI, GeminiSettings()),
        (
            ProviderType.OPENAI_COMPATIBLE,
            OpenAICompatibleSettings(base_url="https://compatible.example.com"),
        ),
    ],
)
def test_every_provider_settings_variant_round_trips(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
    provider_type: ProviderType,
    settings: ProviderSettings,
) -> None:
    organization_public_id = _seed_organization(migrated_engine)
    persistence = _persistence(persistence_async_session_factory)
    provider = replace(
        _provider(organization_public_id),
        provider_type=provider_type,
        settings=settings,
    )

    asyncio.run(persistence.create_provider(provider))

    configuration = asyncio.run(
        persistence.load_configuration(organization_public_id=organization_public_id)
    )
    assert configuration is not None
    assert configuration.providers == (provider,)


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


def test_update_provider_preserves_existing_credential_reference(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id = _seed_organization(migrated_engine)
    credential_reference = CredentialReference(uuid4())
    persistence = _persistence(persistence_async_session_factory)
    provider = _provider(
        organization_public_id,
        credential_reference=credential_reference,
    )
    asyncio.run(persistence.create_provider(provider))

    asyncio.run(
        persistence.update_provider_configuration(
            organization_public_id=organization_public_id,
            provider_id=provider.provider_id,
            display_name="Updated OpenAI",
            settings=None,
        )
    )

    configuration = asyncio.run(
        persistence.load_configuration(organization_public_id=organization_public_id)
    )
    assert configuration is not None
    assert configuration.providers[0].display_name == "Updated OpenAI"
    assert configuration.providers[0].credential_reference == credential_reference


def test_update_provider_url_change_clears_credential_reference_atomically(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id = _seed_organization(migrated_engine)
    credential_reference = CredentialReference(uuid4())
    persistence = _persistence(persistence_async_session_factory)
    provider = replace(
        _provider(
            organization_public_id,
            credential_reference=credential_reference,
        ),
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        settings=OpenAICompatibleSettings(base_url="https://first.example.com"),
    )
    asyncio.run(persistence.create_provider(provider))

    result = asyncio.run(
        persistence.update_provider_configuration(
            organization_public_id=organization_public_id,
            provider_id=provider.provider_id,
            display_name="Updated display name",
            settings=OpenAICompatibleSettings(base_url="https://second.example.com"),
        )
    )

    assert result.cleared_credential_reference == credential_reference
    assert result.provider.credential_reference is None
    configuration = asyncio.run(
        persistence.load_configuration(organization_public_id=organization_public_id)
    )
    assert configuration is not None
    assert configuration.providers[0].credential_reference is None


def test_provider_credential_reference_compare_and_set_rejects_stale_reference(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id = _seed_organization(migrated_engine)
    persistence = _persistence(persistence_async_session_factory)
    initial_reference = CredentialReference(uuid4())
    provider = _provider(
        organization_public_id,
        credential_reference=initial_reference,
    )
    asyncio.run(persistence.create_provider(provider))
    winning_reference = CredentialReference(uuid4())
    updated = asyncio.run(
        persistence.set_provider_credential_reference(
            organization_public_id=organization_public_id,
            provider_id=provider.provider_id,
            expected_credential_reference=initial_reference,
            credential_reference=winning_reference,
        )
    )
    assert updated.credential_reference == winning_reference

    with pytest.raises(ModelProviderConflictError):
        asyncio.run(
            persistence.set_provider_credential_reference(
                organization_public_id=organization_public_id,
                provider_id=provider.provider_id,
                expected_credential_reference=initial_reference,
                credential_reference=CredentialReference(uuid4()),
            )
        )

    configuration = asyncio.run(
        persistence.load_configuration(organization_public_id=organization_public_id)
    )
    assert configuration is not None
    assert configuration.providers[0].credential_reference == winning_reference


def test_validation_round_trips_and_connection_changes_reset_it(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id = _seed_organization(migrated_engine)
    reference = CredentialReference(uuid4())
    persistence = _persistence(persistence_async_session_factory)
    provider = replace(
        _provider(organization_public_id, credential_reference=reference),
        provider_type=ProviderType.AZURE_OPENAI,
        settings=AzureOpenAISettings(
            endpoint="https://models.example.com",
            api_version="2026-01-01",
        ),
    )
    asyncio.run(persistence.create_provider(provider))

    validated = asyncio.run(
        persistence.record_provider_validation(
            organization_public_id=organization_public_id,
            provider_id=provider.provider_id,
            expected_settings=provider.settings,
            expected_credential_reference=reference,
            status=ProviderValidationStatus.VALID,
        )
    )

    assert validated.validation_status is ProviderValidationStatus.VALID
    assert validated.last_validated_at is not None
    updated = asyncio.run(
        persistence.update_provider_configuration(
            organization_public_id=organization_public_id,
            provider_id=provider.provider_id,
            display_name=None,
            settings=AzureOpenAISettings(
                endpoint="https://models.example.com",
                api_version="2026-02-01",
            ),
        )
    ).provider
    assert updated.validation_status is ProviderValidationStatus.UNVALIDATED
    assert updated.last_validated_at is None


def test_display_and_enabled_changes_preserve_validation(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id = _seed_organization(migrated_engine)
    reference = CredentialReference(uuid4())
    persistence = _persistence(persistence_async_session_factory)
    provider = _provider(
        organization_public_id,
        credential_reference=reference,
    )
    asyncio.run(persistence.create_provider(provider))
    validated = asyncio.run(
        persistence.record_provider_validation(
            organization_public_id=organization_public_id,
            provider_id=provider.provider_id,
            expected_settings=provider.settings,
            expected_credential_reference=reference,
            status=ProviderValidationStatus.VALID,
        )
    )

    renamed = asyncio.run(
        persistence.update_provider_configuration(
            organization_public_id=organization_public_id,
            provider_id=provider.provider_id,
            display_name="Renamed",
            settings=None,
        )
    ).provider
    disabled = asyncio.run(
        persistence.set_provider_enabled(
            organization_public_id=organization_public_id,
            provider_id=provider.provider_id,
            enabled=False,
        )
    )

    assert renamed.validation_status is ProviderValidationStatus.VALID
    assert renamed.last_validated_at == validated.last_validated_at
    assert disabled.validation_status is ProviderValidationStatus.VALID
    assert disabled.last_validated_at == validated.last_validated_at


def test_stale_validation_result_cannot_validate_new_credential(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id = _seed_organization(migrated_engine)
    old_reference = CredentialReference(uuid4())
    new_reference = CredentialReference(uuid4())
    persistence = _persistence(persistence_async_session_factory)
    provider = _provider(
        organization_public_id,
        credential_reference=old_reference,
    )
    asyncio.run(persistence.create_provider(provider))
    asyncio.run(
        persistence.set_provider_credential_reference(
            organization_public_id=organization_public_id,
            provider_id=provider.provider_id,
            expected_credential_reference=old_reference,
            credential_reference=new_reference,
        )
    )

    with pytest.raises(ModelProviderConflictError):
        asyncio.run(
            persistence.record_provider_validation(
                organization_public_id=organization_public_id,
                provider_id=provider.provider_id,
                expected_settings=provider.settings,
                expected_credential_reference=old_reference,
                status=ProviderValidationStatus.VALID,
            )
        )

    configuration = asyncio.run(
        persistence.load_configuration(organization_public_id=organization_public_id)
    )
    assert configuration is not None
    assert configuration.providers[0].credential_reference == new_reference
    assert (
        configuration.providers[0].validation_status
        is ProviderValidationStatus.UNVALIDATED
    )


def test_concurrent_validation_and_credential_change_never_leave_new_credential_valid(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id = _seed_organization(migrated_engine)
    old_reference = CredentialReference(uuid4())
    new_reference = CredentialReference(uuid4())
    persistence = _persistence(persistence_async_session_factory)
    provider = _provider(
        organization_public_id,
        credential_reference=old_reference,
    )
    asyncio.run(persistence.create_provider(provider))

    async def race() -> tuple[object, object]:
        results = await asyncio.gather(
            persistence.record_provider_validation(
                organization_public_id=organization_public_id,
                provider_id=provider.provider_id,
                expected_settings=provider.settings,
                expected_credential_reference=old_reference,
                status=ProviderValidationStatus.VALID,
            ),
            persistence.set_provider_credential_reference(
                organization_public_id=organization_public_id,
                provider_id=provider.provider_id,
                expected_credential_reference=old_reference,
                credential_reference=new_reference,
            ),
            return_exceptions=True,
        )
        return results[0], results[1]

    _validation_result, credential_result = asyncio.run(race())

    assert isinstance(credential_result, ConfiguredProvider)
    configuration = asyncio.run(
        persistence.load_configuration(organization_public_id=organization_public_id)
    )
    assert configuration is not None
    current = configuration.providers[0]
    assert current.credential_reference == new_reference
    assert current.validation_status is ProviderValidationStatus.UNVALIDATED
    assert current.last_validated_at is None


def test_concurrent_credential_reference_switch_allows_exactly_one_winner(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id = _seed_organization(migrated_engine)
    persistence = _persistence(persistence_async_session_factory)
    original_reference = CredentialReference(uuid4())
    provider = _provider(
        organization_public_id,
        credential_reference=original_reference,
    )
    asyncio.run(persistence.create_provider(provider))
    candidates = (CredentialReference(uuid4()), CredentialReference(uuid4()))

    async def race() -> list[ConfiguredProvider | BaseException]:
        return list(
            await asyncio.gather(
                *(
                    persistence.set_provider_credential_reference(
                        organization_public_id=organization_public_id,
                        provider_id=provider.provider_id,
                        expected_credential_reference=original_reference,
                        credential_reference=candidate,
                    )
                    for candidate in candidates
                ),
                return_exceptions=True,
            )
        )

    results = asyncio.run(race())

    winners = [result for result in results if isinstance(result, ConfiguredProvider)]
    conflicts = [
        result for result in results if isinstance(result, ModelProviderConflictError)
    ]
    assert len(winners) == 1
    assert len(conflicts) == 1
    configuration = asyncio.run(
        persistence.load_configuration(organization_public_id=organization_public_id)
    )
    assert configuration is not None
    assert (
        configuration.providers[0].credential_reference
        == winners[0].credential_reference
    )


def test_postgresql_persists_only_the_opaque_credential_reference(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id = _seed_organization(migrated_engine)
    reference = CredentialReference(uuid4())
    provider = _provider(
        organization_public_id,
        credential_reference=reference,
    )
    asyncio.run(
        _persistence(persistence_async_session_factory).create_provider(provider)
    )

    with Session(migrated_engine) as session:
        record = session.scalar(
            select(ModelProviderRecord).where(
                ModelProviderRecord.public_id == provider.provider_id.value
            )
        )
        assert record is not None
        assert record.credential_reference == reference.value
        assert record.settings_json == {}
        assert not any("secret" in column.name for column in record.__table__.columns)


def test_delete_provider_with_models_is_explicitly_restricted(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id = _seed_organization(migrated_engine)
    persistence = _persistence(persistence_async_session_factory)
    provider = _provider(organization_public_id)
    model = _chat_model(organization_public_id, provider.provider_id)
    asyncio.run(persistence.create_provider(provider))
    asyncio.run(persistence.create_model(model))

    with pytest.raises(
        ModelProviderDeleteRestrictedError,
        match=r"^Configured provider is still referenced by models$",
    ):
        asyncio.run(
            persistence.delete_provider(
                organization_public_id=organization_public_id,
                provider_id=provider.provider_id,
            )
        )

    configuration = asyncio.run(
        persistence.load_configuration(organization_public_id=organization_public_id)
    )
    assert configuration is not None
    assert configuration.providers == (provider,)
    assert configuration.models == (model,)


def test_delete_current_default_model_is_explicitly_restricted(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id = _seed_organization(migrated_engine)
    persistence = _persistence(persistence_async_session_factory)
    provider, model = asyncio.run(
        _create_complete_configuration(persistence, organization_public_id)
    )

    with pytest.raises(
        ModelProviderDeleteRestrictedError,
        match=r"^Configured model is selected as a default$",
    ):
        asyncio.run(
            persistence.delete_model(
                organization_public_id=organization_public_id,
                model_id=model.model_id,
            )
        )

    configuration = asyncio.run(
        persistence.load_configuration(organization_public_id=organization_public_id)
    )
    assert configuration is not None
    assert configuration.providers == (provider,)
    assert configuration.models == (model,)
    assert configuration.defaults.chat == model.model_id


def test_changing_existing_default_advances_updated_at(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id = _seed_organization(migrated_engine)
    persistence = _persistence(persistence_async_session_factory)
    provider = _provider(organization_public_id)
    first_model = _chat_model(organization_public_id, provider.provider_id)
    second_model = _chat_model(organization_public_id, provider.provider_id)
    asyncio.run(persistence.create_provider(provider))
    asyncio.run(persistence.create_model(first_model))
    asyncio.run(persistence.create_model(second_model))
    asyncio.run(
        persistence.set_default(
            organization_public_id=organization_public_id,
            model_type=ModelType.CHAT,
            model_id=first_model.model_id,
        )
    )
    old_timestamp = datetime(2000, 1, 1, tzinfo=UTC)
    with Session(migrated_engine) as session:
        default = session.scalar(select(OrganizationModelDefault))
        assert default is not None
        default.updated_at = old_timestamp
        session.commit()

    asyncio.run(
        persistence.set_default(
            organization_public_id=organization_public_id,
            model_type=ModelType.CHAT,
            model_id=second_model.model_id,
        )
    )

    with Session(migrated_engine) as session:
        default = session.scalar(select(OrganizationModelDefault))
        assert default is not None
        assert default.updated_at > old_timestamp
    configuration = asyncio.run(
        persistence.load_configuration(organization_public_id=organization_public_id)
    )
    assert configuration is not None
    assert configuration.defaults.chat == second_model.model_id


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
        operation = persistence.set_provider_enabled(
            organization_public_id=organization_public_id,
            provider_id=provider.provider_id,
            enabled=False,
        )
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


def test_concurrent_provider_configuration_and_enabled_updates_preserve_both(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id = _seed_organization(migrated_engine)
    persistence = _persistence(persistence_async_session_factory)
    provider = _provider(organization_public_id)
    asyncio.run(persistence.create_provider(provider))

    async def race() -> None:
        await asyncio.gather(
            persistence.update_provider_configuration(
                organization_public_id=organization_public_id,
                provider_id=provider.provider_id,
                display_name="Renamed",
                settings=None,
            ),
            persistence.set_provider_enabled(
                organization_public_id=organization_public_id,
                provider_id=provider.provider_id,
                enabled=False,
            ),
        )

    asyncio.run(race())

    configuration = asyncio.run(
        persistence.load_configuration(organization_public_id=organization_public_id)
    )
    assert configuration is not None
    assert configuration.providers[0].display_name == "Renamed"
    assert configuration.providers[0].enabled is False


def test_display_only_update_preserves_new_url_and_credential_from_other_admin(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id = _seed_organization(migrated_engine)
    persistence = _persistence(persistence_async_session_factory)
    old_reference = CredentialReference(uuid4())
    provider = replace(
        _provider(
            organization_public_id,
            credential_reference=old_reference,
        ),
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        settings=OpenAICompatibleSettings(base_url="https://old.example.com"),
    )
    asyncio.run(persistence.create_provider(provider))
    url_update = asyncio.run(
        persistence.update_provider_configuration(
            organization_public_id=organization_public_id,
            provider_id=provider.provider_id,
            display_name=None,
            settings=OpenAICompatibleSettings(base_url="https://new.example.com"),
        )
    )
    assert url_update.cleared_credential_reference == old_reference
    new_reference = CredentialReference(uuid4())
    asyncio.run(
        persistence.set_provider_credential_reference(
            organization_public_id=organization_public_id,
            provider_id=provider.provider_id,
            expected_credential_reference=None,
            credential_reference=new_reference,
        )
    )

    asyncio.run(
        persistence.update_provider_configuration(
            organization_public_id=organization_public_id,
            provider_id=provider.provider_id,
            display_name="Stale form rename",
            settings=None,
        )
    )

    configuration = asyncio.run(
        persistence.load_configuration(organization_public_id=organization_public_id)
    )
    assert configuration is not None
    current = configuration.providers[0]
    assert current.display_name == "Stale form rename"
    assert current.settings == OpenAICompatibleSettings(
        base_url="https://new.example.com"
    )
    assert current.credential_reference == new_reference
