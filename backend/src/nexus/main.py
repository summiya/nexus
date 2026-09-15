from fastapi import FastAPI

from nexus.api.router import api_router
from nexus.config.settings import settings
from nexus.errors.handlers import register_exception_handlers
from nexus.logging import configure_logging, get_logger
from nexus.middleware import RequestContextMiddleware

configure_logging(settings.log_level)
logger = get_logger("nexus")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.api_version,
        description="NEXUS foundation application",
        debug=settings.debug,
    )

    @app.on_event("startup")
    async def startup_event() -> None:
        logger.info("application_started")

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_prefix)
    app.add_middleware(RequestContextMiddleware)
    return app


app = create_app()
