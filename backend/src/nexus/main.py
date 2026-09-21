from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nexus.api.router import api_router
from nexus.authentication.gateways import RateLimiter
from nexus.composition.root import AppContainer, build_app_container
from nexus.config.settings import Settings, load_settings
from nexus.errors.handlers import register_exception_handlers
from nexus.events import EventPublisher
from nexus.infrastructure.mailer import EmailProvider
from nexus.infrastructure.persistence.session import Database
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
        container: AppContainer = app.state.container
        container.close()
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

    container = build_app_container(
        resolved_settings,
        event_publisher=event_publisher,
        llm_gateway=llm_gateway,
        database=database,
        rate_limiter=rate_limiter,
        email_provider=email_provider,
    )
    app.state.container = container

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
