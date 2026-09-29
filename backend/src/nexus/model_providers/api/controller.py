"""Organization model-provider HTTP controller."""

from uuid import UUID

from fastapi import APIRouter, Response, status

from nexus.authentication.api.security import CurrentAuthContextDep
from nexus.errors import ErrorCode, NexusError
from nexus.model_providers.api.dependencies import (
    ConfiguredModelDeleterDep,
    ConfiguredModelEnabledSetterDep,
    ConfiguredModelListDep,
    ConfiguredModelRegistrarDep,
    ProviderCatalogDep,
    ProviderCreatorDep,
    ProviderCredentialSetterDep,
    ProviderDeleterDep,
    ProviderDep,
    ProviderEnabledSetterDep,
    ProviderListDep,
    ProviderModelDiscoveryDep,
    ProviderUpdaterDep,
    ProviderValidatorDep,
)
from nexus.model_providers.api.schemas import (
    ConfiguredModelResponseBody,
    ConfiguredProviderResponseBody,
    CreateProviderRequestBody,
    DiscoveredModelRegistrationRequestBody,
    ListConfiguredModelsResponseBody,
    ListConfiguredProvidersResponseBody,
    ModelCandidateResponseBody,
    ProviderCatalogItemResponseBody,
    ProviderCatalogResponseBody,
    ProviderCredentialStateResponseBody,
    ProviderModelCatalogResponseBody,
    ProviderValidationResponseBody,
    RegisterConfiguredModelsRequestBody,
    SetConfiguredModelEnabledRequestBody,
    SetProviderCredentialRequestBody,
    SetProviderEnabledRequestBody,
    UpdateProviderRequestBody,
)
from nexus.model_providers.application import ConfiguredModelItem
from nexus.model_providers.domain import (
    ConfiguredProvider,
    ModelCapability,
    ModelProviderConfigurationError,
    ModelType,
    ProviderCredentialSecret,
    provider_settings_to_mapping,
)

router = APIRouter(prefix="/model-providers", tags=["model-providers"])
configured_models_router = APIRouter(
    prefix="/configured-models", tags=["model-providers"]
)


@router.get("/catalog", response_model=ProviderCatalogResponseBody)
async def list_provider_catalog(
    response: Response,
    auth_context: CurrentAuthContextDep,
    service: ProviderCatalogDep,
) -> ProviderCatalogResponseBody:
    items = await service.execute(
        organization_public_id=auth_context.organization_public_id,
        user_public_id=auth_context.user_public_id,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return ProviderCatalogResponseBody(
        items=[
            ProviderCatalogItemResponseBody(
                provider_type=item.provider_type,
                display_name=item.display_name,
                required_settings=list(item.required_settings),
            )
            for item in items
        ]
    )


@router.get("", response_model=ListConfiguredProvidersResponseBody)
async def list_configured_providers(
    response: Response,
    auth_context: CurrentAuthContextDep,
    service: ProviderListDep,
) -> ListConfiguredProvidersResponseBody:
    providers = await service.execute(
        organization_public_id=auth_context.organization_public_id,
        user_public_id=auth_context.user_public_id,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return ListConfiguredProvidersResponseBody(
        items=[_to_response(provider) for provider in providers]
    )


@router.get("/{provider_public_id}", response_model=ConfiguredProviderResponseBody)
async def get_configured_provider(
    provider_public_id: UUID,
    response: Response,
    auth_context: CurrentAuthContextDep,
    service: ProviderDep,
) -> ConfiguredProviderResponseBody:
    provider = await service.execute(
        organization_public_id=auth_context.organization_public_id,
        user_public_id=auth_context.user_public_id,
        provider_public_id=provider_public_id,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return _to_response(provider)


@router.post(
    "",
    response_model=ConfiguredProviderResponseBody,
    status_code=status.HTTP_201_CREATED,
)
async def create_configured_provider(
    body: CreateProviderRequestBody,
    response: Response,
    auth_context: CurrentAuthContextDep,
    service: ProviderCreatorDep,
) -> ConfiguredProviderResponseBody:
    provider = await service.execute(
        organization_public_id=auth_context.organization_public_id,
        user_public_id=auth_context.user_public_id,
        provider_type=body.provider_type,
        display_name=body.display_name,
        settings=body.settings,
        enabled=body.enabled,
    )
    response.headers["Cache-Control"] = "no-store"
    return _to_response(provider)


@router.put("/{provider_public_id}", response_model=ConfiguredProviderResponseBody)
async def update_configured_provider(
    provider_public_id: UUID,
    body: UpdateProviderRequestBody,
    response: Response,
    auth_context: CurrentAuthContextDep,
    service: ProviderUpdaterDep,
) -> ConfiguredProviderResponseBody:
    provider = await service.execute(
        organization_public_id=auth_context.organization_public_id,
        user_public_id=auth_context.user_public_id,
        provider_public_id=provider_public_id,
        display_name=body.display_name,
        settings=body.settings,
    )
    response.headers["Cache-Control"] = "no-store"
    return _to_response(provider)


@router.patch(
    "/{provider_public_id}/enabled", response_model=ConfiguredProviderResponseBody
)
async def set_configured_provider_enabled(
    provider_public_id: UUID,
    body: SetProviderEnabledRequestBody,
    response: Response,
    auth_context: CurrentAuthContextDep,
    service: ProviderEnabledSetterDep,
) -> ConfiguredProviderResponseBody:
    provider = await service.execute(
        organization_public_id=auth_context.organization_public_id,
        user_public_id=auth_context.user_public_id,
        provider_public_id=provider_public_id,
        enabled=body.enabled,
    )
    response.headers["Cache-Control"] = "no-store"
    return _to_response(provider)


@router.put(
    "/{provider_public_id}/credential",
    response_model=ProviderCredentialStateResponseBody,
)
async def set_configured_provider_credential(
    provider_public_id: UUID,
    body: SetProviderCredentialRequestBody,
    response: Response,
    auth_context: CurrentAuthContextDep,
    service: ProviderCredentialSetterDep,
) -> ProviderCredentialStateResponseBody:
    try:
        secret = ProviderCredentialSecret(body.credential.get_secret_value())
    except ModelProviderConfigurationError as exc:
        raise NexusError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
    provider = await service.execute(
        organization_public_id=auth_context.organization_public_id,
        user_public_id=auth_context.user_public_id,
        provider_public_id=provider_public_id,
        secret=secret,
    )
    response.headers["Cache-Control"] = "no-store"
    return ProviderCredentialStateResponseBody(
        credential_configured=provider.credential_reference is not None
    )


@router.post(
    "/{provider_public_id}/validate",
    response_model=ProviderValidationResponseBody,
)
async def validate_configured_provider(
    provider_public_id: UUID,
    response: Response,
    auth_context: CurrentAuthContextDep,
    service: ProviderValidatorDep,
) -> ProviderValidationResponseBody:
    provider = await service.execute(
        organization_public_id=auth_context.organization_public_id,
        user_public_id=auth_context.user_public_id,
        provider_public_id=provider_public_id,
    )
    if provider.last_validated_at is None:  # guarded by the domain contract
        raise RuntimeError("Recorded provider validation has no timestamp")
    response.headers["Cache-Control"] = "no-store"
    return ProviderValidationResponseBody(
        status=provider.validation_status,
        last_validated_at=provider.last_validated_at,
    )


@router.get(
    "/{provider_public_id}/models",
    response_model=ProviderModelCatalogResponseBody,
)
async def discover_configured_provider_models(
    provider_public_id: UUID,
    response: Response,
    auth_context: CurrentAuthContextDep,
    service: ProviderModelDiscoveryDep,
) -> ProviderModelCatalogResponseBody:
    candidates = await service.execute(
        organization_public_id=auth_context.organization_public_id,
        user_public_id=auth_context.user_public_id,
        provider_public_id=provider_public_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return ProviderModelCatalogResponseBody(
        items=[
            ModelCandidateResponseBody(
                provider_model_name=candidate.provider_model_name,
                display_name=candidate.display_name,
                model_type=candidate.model_type,
                capabilities=sorted(
                    candidate.capabilities,
                    key=lambda capability: capability.value,
                ),
                embedding_dimension=candidate.embedding_dimension,
            )
            for candidate in candidates
        ]
    )


@configured_models_router.get("", response_model=ListConfiguredModelsResponseBody)
async def list_configured_models(
    response: Response,
    auth_context: CurrentAuthContextDep,
    service: ConfiguredModelListDep,
    provider_public_id: UUID | None = None,
    model_type: ModelType | None = None,
    capability: ModelCapability | None = None,
    enabled: bool | None = None,
) -> ListConfiguredModelsResponseBody:
    models = await service.execute(
        organization_public_id=auth_context.organization_public_id,
        user_public_id=auth_context.user_public_id,
        provider_public_id=provider_public_id,
        model_type=model_type,
        capability=capability,
        enabled=enabled,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return ListConfiguredModelsResponseBody(
        items=[_model_to_response(item) for item in models]
    )


@router.post(
    "/{provider_public_id}/configured-models",
    response_model=ListConfiguredModelsResponseBody,
    status_code=status.HTTP_201_CREATED,
)
async def register_configured_models(
    provider_public_id: UUID,
    body: RegisterConfiguredModelsRequestBody,
    response: Response,
    auth_context: CurrentAuthContextDep,
    service: ConfiguredModelRegistrarDep,
) -> ListConfiguredModelsResponseBody:
    if isinstance(body, DiscoveredModelRegistrationRequestBody):
        models = await service.register_discovered(
            organization_public_id=auth_context.organization_public_id,
            user_public_id=auth_context.user_public_id,
            provider_public_id=provider_public_id,
            provider_model_names=tuple(body.provider_model_names),
        )
    else:
        models = await service.register_manual(
            organization_public_id=auth_context.organization_public_id,
            user_public_id=auth_context.user_public_id,
            provider_public_id=provider_public_id,
            provider_model_name=body.provider_model_name,
            display_name=body.display_name,
            model_type=body.model_type,
            capabilities=frozenset(body.capabilities),
            embedding_dimension=body.embedding_dimension,
        )
    response.headers["Cache-Control"] = "no-store"
    return ListConfiguredModelsResponseBody(
        items=[_model_to_response(item) for item in models]
    )


@configured_models_router.patch(
    "/{model_public_id}/enabled",
    response_model=ConfiguredModelResponseBody,
)
async def set_configured_model_enabled(
    model_public_id: UUID,
    body: SetConfiguredModelEnabledRequestBody,
    response: Response,
    auth_context: CurrentAuthContextDep,
    service: ConfiguredModelEnabledSetterDep,
) -> ConfiguredModelResponseBody:
    item = await service.execute(
        organization_public_id=auth_context.organization_public_id,
        user_public_id=auth_context.user_public_id,
        model_public_id=model_public_id,
        enabled=body.enabled,
    )
    response.headers["Cache-Control"] = "no-store"
    return _model_to_response(item)


@configured_models_router.delete(
    "/{model_public_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_configured_model(
    model_public_id: UUID,
    auth_context: CurrentAuthContextDep,
    service: ConfiguredModelDeleterDep,
) -> Response:
    await service.execute(
        organization_public_id=auth_context.organization_public_id,
        user_public_id=auth_context.user_public_id,
        model_public_id=model_public_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{provider_public_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_configured_provider(
    provider_public_id: UUID,
    auth_context: CurrentAuthContextDep,
    service: ProviderDeleterDep,
) -> Response:
    await service.execute(
        organization_public_id=auth_context.organization_public_id,
        user_public_id=auth_context.user_public_id,
        provider_public_id=provider_public_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _to_response(provider: ConfiguredProvider) -> ConfiguredProviderResponseBody:
    return ConfiguredProviderResponseBody(
        public_id=provider.provider_id.value,
        provider_type=provider.provider_type,
        display_name=provider.display_name,
        settings=provider_settings_to_mapping(provider.settings),
        enabled=provider.enabled,
        credential_configured=provider.credential_reference is not None,
        validation_status=provider.validation_status,
        last_validated_at=provider.last_validated_at,
    )


def _model_to_response(item: ConfiguredModelItem) -> ConfiguredModelResponseBody:
    model = item.model
    return ConfiguredModelResponseBody(
        public_id=model.model_id.value,
        provider_public_id=model.provider_id.value,
        provider_type=item.provider_type,
        provider_model_name=model.provider_model_name,
        display_name=model.display_name,
        model_type=model.model_type,
        capabilities=sorted(model.capabilities, key=lambda item: item.value),
        embedding_dimension=model.embedding_dimension,
        enabled=model.enabled,
    )


__all__ = ["configured_models_router", "router"]
