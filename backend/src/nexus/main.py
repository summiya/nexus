from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nexus.api.composition.authentication import (
    AuthenticationComposition,
    build_authentication_composition,
)
from nexus.api.composition.conversations import (
    ConversationComposition,
    build_conversation_composition,
)
from nexus.api.composition.llm import LLMComposition, build_llm_composition
from nexus.api.router import api_router
from nexus.config.settings import Settings, load_settings
from nexus.errors.handlers import register_exception_handlers
from nexus.events import EventPublisher, InProcessEventPublisher
from nexus.infrastructure.mailer import EmailProvider
from nexus.infrastructure.persistence.session import Database, build_database
from nexus.infrastructure.rate_limit import RateLimiter
from nexus.llm.ports import LLMGateway
from nexus.logging import configure_logging, get_logger
from nexus.middleware import RequestContextMiddleware

logger = get_logger("nexus")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Own application-wide startup and shutdown behavior."""
    logger.info("application_started")
    try:
        yield
    finally:
        authentication: AuthenticationComposition = app.state.authentication
        database: Database = app.state.database
        try:
            authentication.close()
        finally:
            database.dispose()
            logger.info("application_stopped")


def create_app(
    app_settings: Settings | None = None,
    event_publisher: EventPublisher | None = None,
    llm_gateway: LLMGateway | None = None,
    database: Database | None = None,
    rate_limiter: RateLimiter | None = None,
    email_provider: EmailProvider | None = None,
) -> FastAPI:
    """Compose one NEXUS FastAPI application from explicit dependencies."""
    resolved_settings = app_settings or load_settings()
    configure_logging(resolved_settings.log_level)

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.api_version,
        description="NEXUS foundation application",
        debug=resolved_settings.debug,
        lifespan=lifespan,
    )

    llm: LLMComposition = build_llm_composition(
        resolved_settings,
        gateway=llm_gateway,
    )
    resolved_database = (
        database
        if database is not None
        else build_database(resolved_settings.database_url)
    )
    authentication: AuthenticationComposition | None = None
    try:
        authentication = build_authentication_composition(
            resolved_settings,
            rate_limiter=rate_limiter,
            email_provider=email_provider,
        )
        conversations: ConversationComposition = build_conversation_composition(
            resolved_settings,
            llm_stream=llm.stream,
            model_policy=llm.model_policy,
            session_factory=resolved_database.session_factory,
        )
    except Exception:
        if authentication is not None:
            authentication.close()
        resolved_database.dispose()
        raise

    app.state.settings = resolved_settings
    app.state.database = resolved_database
    app.state.authentication = authentication
    app.state.event_publisher = (
        event_publisher
        if event_publisher is not None
        else InProcessEventPublisher()
    )
    app.state.llm = llm
    app.state.conversations = conversations

    register_exception_handlers(app)
    app.include_router(api_router, prefix=resolved_settings.api_prefix)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)
    return app
