from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from nexus.conversations.application.create_conversation import CreateConversation
from nexus.conversations.application.events import GenerationCompleted
from nexus.conversations.application.stream_message import (
    StreamConversationMessage,
    StreamConversationMessageRequest,
)
from nexus.conversations.domain import GenerationStatus
from nexus.infrastructure.persistence.conversation import (
    SqlAlchemyConversationPersistence,
)
from nexus.infrastructure.persistence.model_provider import (
    SqlAlchemyModelProviderPersistence,
)
from nexus.infrastructure.persistence.models.generation import (
    Generation as GenerationRecord,
)
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.infrastructure.persistence.models.user import User
from nexus.llm.domain import (
    LLMCompletedEvent,
    LLMEvent,
    LLMFinishReason,
    LLMRequest,
    LLMResponse,
    LLMStartedEvent,
    LLMTextDeltaEvent,
)
from nexus.model_providers.application import (
    CreateModelProvider,
    ListSelectableChatModels,
    ProviderDiscoveryPolicy,
    ProviderValidationPolicy,
    RegisterConfiguredModels,
    ResolveChatModel,
    SetDefaultModel,
    SetModelProviderCredential,
    SetModelProviderEnabled,
    ValidateModelProvider,
)
from nexus.model_providers.application._provider_model_discovery import (
    ProviderModelDiscovery,
)
from nexus.model_providers.domain import (
    CredentialReference,
    ModelCandidate,
    ModelCapability,
    ModelType,
    OpenAISettings,
    OrganizationProviderId,
    ProviderCredentialSecret,
    ProviderSettings,
    ProviderType,
    ProviderValidationStatus,
    ResolvedChatModel,
)


class AllowAllPermissions:
    async def has_permission(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        permission_key: str,
    ) -> bool:
        del organization_public_id, user_public_id, permission_key
        return True


class AllowAllRateLimits:
    async def allow(self, *, key: str, limit: int, window_seconds: int) -> bool:
        del key, limit, window_seconds
        return True


class MemoryCredentialStore:
    def __init__(self) -> None:
        self.secrets: dict[
            tuple[UUID, OrganizationProviderId, CredentialReference],
            ProviderCredentialSecret,
        ] = {}

    async def put(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        credential_reference: CredentialReference,
        secret: ProviderCredentialSecret,
    ) -> None:
        self.secrets[(organization_public_id, provider_id, credential_reference)] = (
            secret
        )

    async def resolve(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        credential_reference: CredentialReference,
    ) -> ProviderCredentialSecret:
        return self.secrets[(organization_public_id, provider_id, credential_reference)]

    async def delete(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        credential_reference: CredentialReference,
    ) -> None:
        self.secrets.pop(
            (organization_public_id, provider_id, credential_reference), None
        )


class ValidProviderValidator:
    async def validate(
        self,
        *,
        provider_type: ProviderType,
        settings: ProviderSettings,
        secret: ProviderCredentialSecret,
    ) -> ProviderValidationStatus:
        assert provider_type is ProviderType.OPENAI
        assert settings == OpenAISettings()
        assert secret.reveal() == "vertical-test-secret"
        return ProviderValidationStatus.VALID


class TestProviderCatalog:
    async def discover(
        self,
        *,
        provider_type: ProviderType,
        settings: ProviderSettings,
        secret: ProviderCredentialSecret,
    ) -> tuple[ModelCandidate, ...]:
        assert provider_type is ProviderType.OPENAI
        assert settings == OpenAISettings()
        assert secret.reveal() == "vertical-test-secret"
        return (
            ModelCandidate(
                provider_model_name="gpt-5-test",
                display_name="GPT-5 Test",
                model_type=ModelType.CHAT,
                capabilities=frozenset({ModelCapability.STREAMING}),
            ),
        )


class CapturingRuntimeGateway:
    def __init__(self) -> None:
        self.targets: list[ResolvedChatModel] = []
        self.requests: list[LLMRequest] = []

    async def generate(
        self, *, request: LLMRequest, target: ResolvedChatModel
    ) -> LLMResponse:
        del request, target
        raise NotImplementedError

    def stream(
        self, *, request: LLMRequest, target: ResolvedChatModel
    ) -> AsyncIterator[LLMEvent]:
        self.requests.append(request)
        self.targets.append(target)
        return _successful_stream()


async def _successful_stream() -> AsyncIterator[LLMEvent]:
    yield LLMStartedEvent()
    yield LLMTextDeltaEvent(delta="Hello from the configured model")
    yield LLMCompletedEvent(finish_reason=LLMFinishReason.STOP)


def _seed_actor(engine: Engine) -> tuple[UUID, UUID]:
    organization_public_id = uuid4()
    user_public_id = uuid4()
    with Session(engine) as session:
        organization = Organization(
            public_id=organization_public_id,
            name="Vertical Model Organization",
            slug=f"vertical-model-{uuid4().hex[:12]}",
            status="active",
        )
        session.add(
            User(
                public_id=user_public_id,
                organization=organization,
                email=f"{uuid4().hex}@example.com",
                status="active",
            )
        )
        session.commit()
    return organization_public_id, user_public_id


async def _exercise_model_to_chat_flow(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    organization_public_id: UUID,
    user_public_id: UUID,
) -> tuple[UUID, UUID, CapturingRuntimeGateway]:
    model_persistence = SqlAlchemyModelProviderPersistence(session_factory)
    conversation_persistence = SqlAlchemyConversationPersistence(session_factory)
    permission_checker = AllowAllPermissions()
    credential_store = MemoryCredentialStore()
    rate_limiter = AllowAllRateLimits()

    provider = await CreateModelProvider(
        persistence=model_persistence,
        permission_checker=permission_checker,
    ).execute(
        organization_public_id=organization_public_id,
        user_public_id=user_public_id,
        provider_type=ProviderType.OPENAI,
        display_name="Production OpenAI",
        settings={},
        enabled=False,
    )
    assert not provider.enabled

    provider = await SetModelProviderCredential(
        persistence=model_persistence,
        permission_checker=permission_checker,
        credential_store=credential_store,
    ).execute(
        organization_public_id=organization_public_id,
        user_public_id=user_public_id,
        provider_public_id=provider.provider_id.value,
        secret=ProviderCredentialSecret("vertical-test-secret"),
    )
    provider = await ValidateModelProvider(
        persistence=model_persistence,
        permission_checker=permission_checker,
        credential_store=credential_store,
        validator=ValidProviderValidator(),
        rate_limiter=rate_limiter,
        policy=ProviderValidationPolicy(
            provider_max_requests=2,
            provider_window_seconds=10,
            organization_max_requests=10,
            organization_window_seconds=60,
        ),
    ).execute(
        organization_public_id=organization_public_id,
        user_public_id=user_public_id,
        provider_public_id=provider.provider_id.value,
    )
    provider = await SetModelProviderEnabled(
        persistence=model_persistence,
        permission_checker=permission_checker,
    ).execute(
        organization_public_id=organization_public_id,
        user_public_id=user_public_id,
        provider_public_id=provider.provider_id.value,
        enabled=True,
    )

    discovery = ProviderModelDiscovery(
        persistence=model_persistence,
        credential_store=credential_store,
        catalog=TestProviderCatalog(),
        rate_limiter=rate_limiter,
        policy=ProviderDiscoveryPolicy(
            provider_max_requests=2,
            provider_window_seconds=10,
            organization_max_requests=10,
            organization_window_seconds=60,
        ),
    )
    registered = await RegisterConfiguredModels(
        persistence=model_persistence,
        permission_checker=permission_checker,
        discovery=discovery,
    ).register_discovered(
        organization_public_id=organization_public_id,
        user_public_id=user_public_id,
        provider_public_id=provider.provider_id.value,
        provider_model_names=("gpt-5-test",),
    )
    model = registered[0].model

    defaults = await SetDefaultModel(
        persistence=model_persistence,
        permission_checker=permission_checker,
    ).execute(
        organization_public_id=organization_public_id,
        user_public_id=user_public_id,
        model_type=ModelType.CHAT,
        model_public_id=model.model_id.value,
    )
    assert defaults.chat == model.model_id

    selectable = await ListSelectableChatModels(persistence=model_persistence).execute(
        organization_public_id=organization_public_id
    )
    assert selectable.default_model_id == model.model_id
    assert selectable.items[0].model_id == model.model_id
    assert selectable.items[0].provider_display_name == "Production OpenAI"

    conversation = await CreateConversation(
        persistence=conversation_persistence
    ).execute(
        organization_public_id=organization_public_id,
        user_public_id=user_public_id,
        title="Vertical configured-model test",
    )
    gateway = CapturingRuntimeGateway()
    lifecycle = await StreamConversationMessage(
        persistence=conversation_persistence,
        resolve_chat_model=ResolveChatModel(
            persistence=model_persistence,
            credential_store=credential_store,
        ),
        runtime_chat_gateway=gateway,
        history_limit=20,
        history_max_chars=10_000,
        message_max_length=2_000,
    ).prepare(
        StreamConversationMessageRequest(
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            conversation_public_id=conversation.public_id,
            content="Use the configured organization model",
            model_id=None,
            idempotency_key=uuid4(),
        )
    )
    events = [event async for event in lifecycle]
    assert isinstance(events[-1], GenerationCompleted)
    assert gateway.targets[0].model_id == model.model_id
    assert gateway.targets[0].provider_id == provider.provider_id
    assert gateway.targets[0].provider_model_name == "gpt-5-test"
    assert gateway.targets[0].credential.reveal() == "vertical-test-secret"
    return model.model_id.value, events[-1].generation_public_id, gateway


def test_provider_configuration_reaches_successful_configured_model_generation(
    migrated_database: tuple[Config, Engine],
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, "head")
    organization_public_id, user_public_id = _seed_actor(engine)

    model_public_id, generation_public_id, gateway = asyncio.run(
        _exercise_model_to_chat_flow(
            session_factory=persistence_async_session_factory,
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
        )
    )

    assert len(gateway.requests) == 1
    with Session(engine) as session:
        generation = session.scalar(
            select(GenerationRecord).where(
                GenerationRecord.public_id == generation_public_id
            )
        )
        assert generation is not None
        assert generation.status == GenerationStatus.COMPLETED.value
        assert generation.configured_model_public_id == model_public_id
