"""Root application composition for NEXUS."""

from __future__ import annotations

from dataclasses import dataclass

from nexus.api.composition.authentication import (
    AuthenticationComposition,
    build_authentication_composition,
)
from nexus.api.composition.conversations import (
    ConversationComposition,
    build_conversation_composition,
)
from nexus.api.composition.llm import LLMComposition, build_llm_composition
from nexus.application.authentication.gateways import RateLimiter
from nexus.config.settings import Settings
from nexus.events import EventPublisher, InProcessEventPublisher
from nexus.infrastructure.mailer import EmailProvider
from nexus.infrastructure.persistence.session import Database, build_database
from nexus.llm.ports import LLMGateway


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
