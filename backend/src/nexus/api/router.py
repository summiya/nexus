from fastapi import APIRouter

from nexus.api.controllers.conversations import router as conversations_router
from nexus.api.health import router as health_router
from nexus.authentication.api.controller import router as auth_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(conversations_router)
api_router.include_router(health_router)
