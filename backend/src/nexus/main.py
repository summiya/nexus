from fastapi import FastAPI

from nexus.api.router import api_router
from nexus.config.logging import configure_logging
from nexus.config.settings import settings
from nexus.errors.handlers import register_exception_handlers

logger = configure_logging(settings.log_level)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.api_version,
        description="NEXUS foundation application",
        debug=settings.debug,
    )

    @app.on_event("startup")
    async def startup_event() -> None:
        logger.info("NEXUS application startup complete")

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
