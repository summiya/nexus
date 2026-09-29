from fastapi import APIRouter

from nexus.api.health import router as health_router
from nexus.authentication.api.controller import router as auth_router
from nexus.conversations.api.controller import router as conversations_router
from nexus.files.api.controller import router as files_router
from nexus.model_providers.api.chat_models import router as chat_models_router
from nexus.model_providers.api.controller import (
    configured_models_router,
)
from nexus.model_providers.api.controller import (
    router as model_providers_router,
)
from nexus.model_providers.api.defaults import router as model_defaults_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(conversations_router)
api_router.include_router(files_router)
api_router.include_router(model_providers_router)
api_router.include_router(configured_models_router)
api_router.include_router(model_defaults_router)
api_router.include_router(chat_models_router)
api_router.include_router(health_router)
