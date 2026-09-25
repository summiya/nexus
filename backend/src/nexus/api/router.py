from fastapi import APIRouter

from nexus.api.health import router as health_router
from nexus.authentication.api.controller import router as auth_router
from nexus.conversations.api.controller import router as conversations_router
from nexus.files.api.controller import router as files_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(conversations_router)
api_router.include_router(files_router)
api_router.include_router(health_router)
