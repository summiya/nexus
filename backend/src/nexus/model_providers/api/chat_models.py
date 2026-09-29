"""Authenticated runtime chat-model selection API."""

from fastapi import APIRouter, Response

from nexus.authentication.api.security import CurrentAuthContextDep
from nexus.model_providers.api.dependencies import SelectableChatModelListDep
from nexus.model_providers.api.schemas import (
    ChatModelResponseBody,
    ListChatModelsResponseBody,
)

router = APIRouter(prefix="/chat-models", tags=["chat-models"])


@router.get("", response_model=ListChatModelsResponseBody)
async def list_chat_models(
    response: Response,
    auth_context: CurrentAuthContextDep,
    service: SelectableChatModelListDep,
) -> ListChatModelsResponseBody:
    result = await service.execute(
        organization_public_id=auth_context.organization_public_id,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return ListChatModelsResponseBody(
        items=[
            ChatModelResponseBody(
                public_id=item.model_id.value,
                display_name=item.display_name,
                provider_type=item.provider_type,
                provider_display_name=item.provider_display_name,
            )
            for item in result.items
        ],
        default_model_public_id=(
            result.default_model_id.value
            if result.default_model_id is not None
            else None
        ),
    )


__all__ = ["router"]
