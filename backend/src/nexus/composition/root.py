"""Root application composition for NEXUS."""

from __future__ import annotations

from asyncio import CancelledError
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.composition.authentication import (
    AuthenticationComposition,
    build_authentication_composition,
)
from nexus.composition.files import FileComposition, build_file_composition
from nexus.composition.model_providers import (
    ModelProviderComposition,
    build_model_provider_composition,
)
from nexus.composition.provider_credentials import (
    ProviderCredentialComposition,
    build_provider_credential_composition,
)
from nexus.composition.storage import (
    StorageComposition,
    build_storage_composition,
)
from nexus.config.litellm import require_local_litellm_metadata
from nexus.config.settings import Settings
from nexus.conversations.application import (
    CreateConversation,
    GetConversationMessages,
    ListConversations,
    StreamConversationMessage,
)
from nexus.events import EventPublisher, InProcessEventPublisher
from nexus.files.ports import DownloadGrantIssuer, ObjectStorage, UploadGrantIssuer
from nexus.infrastructure.mailer import EmailProvider
from nexus.infrastructure.persistence.conversation import (
    SqlAlchemyConversationPersistence,
)
from nexus.infrastructure.persistence.session import Database, build_database
from nexus.llm.application import ModelPolicy
from nexus.llm.infrastructure.gateway_factory import create_llm_gateway
from nexus.llm.ports import LLMGateway
from nexus.model_providers.ports import (
    CredentialStore,
    ProviderConfigurationValidator,
    ProviderModelCatalog,
    RuntimeChatGateway,
)
from nexus.ports.rate_limit import RateLimiter


@dataclass(frozen=True)
class LLMComposition:
    """Application-scoped LLM dependencies composed at startup."""

    gateway: LLMGateway
    runtime_gateway: RuntimeChatGateway
    model_policy: ModelPolicy


@dataclass(frozen=True)
class ConversationComposition:
    create: CreateConversation
    get_messages: GetConversationMessages
    list_conversations: ListConversations
    stream_message: StreamConversationMessage


def build_llm_composition(
    app_settings: Settings,
    gateway: LLMGateway | None = None,
    runtime_gateway: RuntimeChatGateway | None = None,
) -> LLMComposition:
    """Build one shared provider-independent LLM gateway and its policy."""

    resolved_gateway = (
        gateway if gateway is not None else create_llm_gateway(app_settings.llm_gateway)
    )
    if runtime_gateway is None:
        # LiteLLM reads its local-metadata setting during import. Keep this
        # import behind startup's fail-closed guard rather than importing
        # LiteLLM while loading the ASGI module.
        from nexus.llm.infrastructure.adapters.litellm.runtime_adapter import (
            LiteLLMRuntimeAdapter,
        )

        runtime_gateway = LiteLLMRuntimeAdapter(
            timeout_seconds=app_settings.model_provider_runtime_timeout_seconds
        )
    return LLMComposition(
        gateway=resolved_gateway,
        runtime_gateway=runtime_gateway,
        model_policy=ModelPolicy.from_models(app_settings.llm_allowed_models),
    )


def build_conversation_composition(
    app_settings: Settings,
    llm_gateway: LLMGateway,
    model_policy: ModelPolicy,
    session_factory: async_sessionmaker[AsyncSession],
) -> ConversationComposition:
    """Build the existing conversation use cases without changing their behavior."""

    persistence = SqlAlchemyConversationPersistence(session_factory)
    return ConversationComposition(
        create=CreateConversation(persistence=persistence),
        get_messages=GetConversationMessages(persistence=persistence),
        list_conversations=ListConversations(persistence=persistence),
        stream_message=StreamConversationMessage(
            persistence=persistence,
            llm_gateway=llm_gateway,
            model_policy=model_policy,
            history_limit=app_settings.conversation_history_limit,
            history_max_chars=app_settings.conversation_history_max_chars,
            message_max_length=app_settings.conversation_message_max_length,
        ),
    )


@dataclass(frozen=True)
class AppContainer:
    """Own all application-scoped dependencies for one FastAPI application."""

    settings: Settings
    database: Database
    authentication: AuthenticationComposition
    llm: LLMComposition
    conversations: ConversationComposition
    files: FileComposition
    event_publisher: EventPublisher
    storage: StorageComposition
    provider_credentials: ProviderCredentialComposition
    model_providers: ModelProviderComposition

    async def close(self) -> None:
        """Release application-scoped resources in dependency order."""

        try:
            self.authentication.close()
        finally:
            try:
                await self.provider_credentials.close()
            finally:
                try:
                    await self.storage.close()
                finally:
                    await self.database.dispose()


async def build_app_container(
    app_settings: Settings,
    *,
    event_publisher: EventPublisher | None = None,
    llm_gateway: LLMGateway | None = None,
    runtime_chat_gateway: RuntimeChatGateway | None = None,
    database: Database | None = None,
    rate_limiter: RateLimiter | None = None,
    email_provider: EmailProvider | None = None,
    object_storage: ObjectStorage | None = None,
    upload_grant_issuer: UploadGrantIssuer | None = None,
    download_grant_issuer: DownloadGrantIssuer | None = None,
    credential_store: CredentialStore | None = None,
    provider_configuration_validator: ProviderConfigurationValidator | None = None,
    provider_model_catalog: ProviderModelCatalog | None = None,
) -> AppContainer:
    """Build one explicit object graph from one settings instance."""

    require_local_litellm_metadata()
    llm = build_llm_composition(
        app_settings,
        gateway=llm_gateway,
        runtime_gateway=runtime_chat_gateway,
    )
    resolved_event_publisher = (
        event_publisher if event_publisher is not None else InProcessEventPublisher()
    )
    authentication = build_authentication_composition(
        app_settings,
        rate_limiter=rate_limiter,
        email_provider=email_provider,
    )
    try:
        resolved_database = (
            database
            if database is not None
            else build_database(app_settings.database_url)
        )
    except Exception as construction_error:
        try:
            authentication.close()
        except (Exception, CancelledError) as cleanup_error:  # noqa: BLE001 - preserve startup failure
            construction_error.add_note(
                "An authentication resource also failed during startup cleanup: "
                f"{type(cleanup_error).__name__}"
            )
        raise

    storage: StorageComposition | None = None
    provider_credentials: ProviderCredentialComposition | None = None
    try:
        conversations = build_conversation_composition(
            app_settings,
            llm_gateway=llm.gateway,
            model_policy=llm.model_policy,
            session_factory=resolved_database.session_factory,
        )
        storage = await build_storage_composition(
            app_settings,
            object_storage=object_storage,
            upload_grant_issuer=upload_grant_issuer,
            download_grant_issuer=download_grant_issuer,
        )
        provider_credentials = await build_provider_credential_composition(
            app_settings,
            credential_store=credential_store,
        )
        model_providers = build_model_provider_composition(
            app_settings=app_settings,
            session_factory=resolved_database.session_factory,
            credential_store=provider_credentials.store,
            rate_limiter=authentication.rate_limiter,
            validator=provider_configuration_validator,
            model_catalog=provider_model_catalog,
        )
        files = build_file_composition(
            app_settings,
            session_factory=resolved_database.session_factory,
            upload_grant_issuer=storage.upload_grant_issuer,
            download_grant_issuer=storage.download_grant_issuer,
            object_storage=storage.object_storage,
        )
    except (Exception, CancelledError) as construction_error:
        try:
            authentication.close()
        except (Exception, CancelledError) as cleanup_error:  # noqa: BLE001 - preserve startup failure
            construction_error.add_note(
                "An authentication resource also failed during startup cleanup: "
                f"{type(cleanup_error).__name__}"
            )
        if storage is not None:
            try:
                await storage.close()
            except (Exception, CancelledError) as cleanup_error:  # noqa: BLE001 - preserve startup failure
                construction_error.add_note(
                    "A storage resource also failed during startup cleanup: "
                    f"{type(cleanup_error).__name__}"
                )
        if provider_credentials is not None:
            try:
                await provider_credentials.close()
            except (Exception, CancelledError) as cleanup_error:  # noqa: BLE001
                construction_error.add_note(
                    "A credential-store resource also failed during startup cleanup: "
                    f"{type(cleanup_error).__name__}"
                )
        try:
            await resolved_database.dispose()
        except (Exception, CancelledError) as cleanup_error:  # noqa: BLE001 - preserve startup failure
            construction_error.add_note(
                "A database resource also failed during startup cleanup: "
                f"{type(cleanup_error).__name__}"
            )
        raise

    return AppContainer(
        settings=app_settings,
        database=resolved_database,
        authentication=authentication,
        llm=llm,
        conversations=conversations,
        files=files,
        event_publisher=resolved_event_publisher,
        storage=storage,
        provider_credentials=provider_credentials,
        model_providers=model_providers,
    )
