from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nexus.api.composition.llm import build_llm_composition
from nexus.api.router import api_router
from nexus.config.settings import Settings, settings
from nexus.errors.handlers import register_exception_handlers
from nexus.events import EventPublisher, InProcessEventPublisher
from nexus.llm.ports import LLMGateway
from nexus.logging import configure_logging, get_logger
from nexus.middleware import RequestContextMiddleware

logger = get_logger("nexus")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Own application-wide startup and shutdown behavior."""
    logger.info("application_started")
    try:
        yield
    finally:
        logger.info("application_stopped")


def create_app(
    app_settings: Settings = settings,
    event_publisher: EventPublisher | None = None,
    llm_gateway: LLMGateway | None = None,
) -> FastAPI:
    """Compose the NEXUS FastAPI application from approved foundation services."""
    configure_logging(app_settings.log_level)

    app = FastAPI(
        title=app_settings.app_name,
        version=app_settings.api_version,
        description="NEXUS foundation application",
        debug=app_settings.debug,
        lifespan=lifespan,
    )

    app.state.event_publisher = event_publisher or InProcessEventPublisher()
    app.state.llm = build_llm_composition(app_settings, gateway=llm_gateway)

    register_exception_handlers(app)
    app.include_router(api_router, prefix=app_settings.api_prefix)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)
    return app


app = create_app()
