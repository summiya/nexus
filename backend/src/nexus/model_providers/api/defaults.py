"""Organization default-model selection HTTP API."""

from fastapi import APIRouter, Response, status

from nexus.authentication.api.security import CurrentAuthContextDep
from nexus.model_providers.api.dependencies import (
    DefaultModelClearerDep,
    DefaultModelGetterDep,
    DefaultModelSetterDep,
)
from nexus.model_providers.api.schemas import (
    ModelDefaultsResponseBody,
    SetModelDefaultRequestBody,
)
from nexus.model_providers.domain import DefaultModelSelection, ModelType

router = APIRouter(prefix="/model-defaults", tags=["model-providers"])


@router.get("", response_model=ModelDefaultsResponseBody)
async def get_model_defaults(
    response: Response,
    auth_context: CurrentAuthContextDep,
    service: DefaultModelGetterDep,
) -> ModelDefaultsResponseBody:
    defaults = await service.execute(
        organization_public_id=auth_context.organization_public_id,
        user_public_id=auth_context.user_public_id,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return _to_response(defaults)


@router.put("/{model_type}", response_model=ModelDefaultsResponseBody)
async def set_model_default(
    model_type: ModelType,
    body: SetModelDefaultRequestBody,
    response: Response,
    auth_context: CurrentAuthContextDep,
    service: DefaultModelSetterDep,
) -> ModelDefaultsResponseBody:
    defaults = await service.execute(
        organization_public_id=auth_context.organization_public_id,
        user_public_id=auth_context.user_public_id,
        model_type=model_type,
        model_public_id=body.model_public_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return _to_response(defaults)


@router.delete("/{model_type}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_model_default(
    model_type: ModelType,
    auth_context: CurrentAuthContextDep,
    service: DefaultModelClearerDep,
) -> Response:
    await service.execute(
        organization_public_id=auth_context.organization_public_id,
        user_public_id=auth_context.user_public_id,
        model_type=model_type,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _to_response(defaults: DefaultModelSelection) -> ModelDefaultsResponseBody:
    return ModelDefaultsResponseBody(
        chat=defaults.chat.value if defaults.chat is not None else None,
        embedding=(
            defaults.embedding.value if defaults.embedding is not None else None
        ),
        reranker=defaults.reranker.value if defaults.reranker is not None else None,
    )


__all__ = ["router"]
