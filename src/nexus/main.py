from fastapi import FastAPI

from nexus.api.router import api_router
from nexus.config.settings import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.api_version,
        description="NEXUS foundation application",
    )
    app.include_router(api_router)
    return app


app = create_app()
