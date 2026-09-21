"""Root application composition for NEXUS."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from nexus.authentication.gateways import RateLimiter
from nexus.composition.authentication import (
    AuthenticationComposition,
    build_authentication_composition,
)
from nexus.config.settings import Settings
from nexus.conversations.application import (
    CreateConversation,
    StreamConversationMessage,
)
from nexus.events import EventPublisher, InProcessEventPublisher
from nexus.infrastructure.mailer import EmailProvider
from nexus.infrastructure.persistence.conversation import (
    SqlAlchemyConversationPersistence,
)
from nexus.infrastructure.persistence.session import Database, build_database
from nexus.llm.application import Generate, ModelPolicy, Stream
from nexus.llm.infrastructure.gateway_factory import create_llm_gateway
from nexus.llm.ports import LLMGateway


@dataclass(frozen=True)
class LLMComposition:
    """Application-scoped LLM dependencies composed at startup."""

    gateway: LLMGateway
    model_policy: ModelPolicy
    generate: Generate
    stream: Stream


@dataclass(frozen=True)
class ConversationComposition:
    create: CreateConversation
    stream_message: StreamConversationMessage


def build_llm_composition(
    app_settings: Settings,
    gateway: LLMGateway | None = None,
) -> LLMComposition:
    """Build LLM use cases around one shared gateway instance."""

    resolved_gateway = (
        gateway if gateway is not None else create_llm_gateway(app_settings.llm_gateway)
    )
    return LLMComposition(
        gateway=resolved_gateway,
        model_policy=ModelPolicy.from_models(app_settings.llm_allowed_models),
        generate=Generate(gateway=resolved_gateway),
        stream=Stream(gateway=resolved_gateway),
    )


def build_conversation_composition(
    app_settings: Settings,
    llm_stream: Stream,
    model_policy: ModelPolicy,
    session_factory: Callable[[], Session],
) -> ConversationComposition:
    """Build the existing conversation use cases without changing their behavior."""

    persistence = SqlAlchemyConversationPersistence(session_factory)
    return ConversationComposition(
        create=CreateConversation(persistence=persistence),
        stream_message=StreamConversationMessage(
            persistence=persistence,
            llm_stream=llm_stream,
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
    event_publisher: EventPublisher

    def close(self) -> None:
        """Release application-scoped resources in dependency order."""

        try:
            self.authentication.close()
        finally:
            self.database.dispose()


def build_app_container(
    app_settings: Settings,
    *,
    event_publisher: EventPublisher | None = None,
    llm_gateway: LLMGateway | None = None,
    database: Database | None = None,
    rate_limiter: RateLimiter | None = None,
    email_provider: EmailProvider | None = None,
) -> AppContainer:
    """Build one explicit object graph from one settings instance."""

    llm = build_llm_composition(app_settings, gateway=llm_gateway)
    resolved_database = (
        database if database is not None else build_database(app_settings.database_url)
    )
    authentication: AuthenticationComposition | None = None
    try:
        authentication = build_authentication_composition(
            app_settings,
            rate_limiter=rate_limiter,
            email_provider=email_provider,
        )
        conversations = build_conversation_composition(
            app_settings,
            llm_stream=llm.stream,
            model_policy=llm.model_policy,
            session_factory=resolved_database.session_factory,
        )
        return AppContainer(
            settings=app_settings,
            database=resolved_database,
            authentication=authentication,
            llm=llm,
            conversations=conversations,
            event_publisher=(
                event_publisher
                if event_publisher is not None
                else InProcessEventPublisher()
            ),
        )
    except Exception:
        if authentication is not None:
            authentication.close()
        resolved_database.dispose()
        raise
