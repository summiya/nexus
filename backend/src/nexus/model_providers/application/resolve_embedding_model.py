"""Organization-scoped embedding-model resolution, without embedding execution."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from nexus.errors import ErrorCode, NexusError
from nexus.model_providers.application._runtime_model_eligibility import (
    is_runtime_provider_eligible,
)
from nexus.model_providers.application._shared import (
    NOT_FOUND,
    conflict,
    credential_unavailable,
    load_configuration,
    unavailable,
)
from nexus.model_providers.domain import (
    ConfiguredModel,
    ConfiguredModelId,
    ModelProviderConfigurationError,
    ModelType,
    OrganizationModelProviderConfiguration,
    ProviderCredentialSecret,
    ResolvedEmbeddingModel,
)
from nexus.model_providers.ports import (
    CredentialNotFoundError,
    CredentialStore,
    CredentialStoreError,
    ModelProviderPersistence,
)

_NO_DEFAULT = "No embedding model is configured."


@dataclass(frozen=True)
class ResolveEmbeddingModel:
    """Resolve one eligible model using already-authorized application tenant context."""

    persistence: ModelProviderPersistence
    credential_store: CredentialStore | None

    async def execute(
        self, *, organization_public_id: UUID, model_id: ConfiguredModelId | None
    ) -> ResolvedEmbeddingModel:
        if (
            not isinstance(organization_public_id, UUID)
            or not organization_public_id.int
            or (
                model_id is not None
                and (
                    not isinstance(model_id, ConfiguredModelId)
                    or not model_id.value.int
                )
            )
        ):
            raise NexusError(
                ErrorCode.VALIDATION_ERROR, "Embedding model selection is invalid."
            )
        try:
            configuration = await load_configuration(
                self.persistence, organization_public_id=organization_public_id
            )
        except ModelProviderConfigurationError as exc:
            raise unavailable() from exc
        if configuration is not None and (
            not isinstance(configuration, OrganizationModelProviderConfiguration)
            or configuration.organization_public_id != organization_public_id
        ):
            raise unavailable()

        model = _resolve_model(configuration, model_id=model_id)
        if model.organization_public_id != organization_public_id:
            raise unavailable()
        dimension = model.embedding_dimension
        if (
            model.enabled is not True
            or model.model_type is not ModelType.EMBEDDING
            or type(dimension) is not int
            or dimension <= 0
        ):
            raise conflict()

        # Model selection proved configuration exists. Keep one detached snapshot.
        assert configuration is not None
        provider = next(
            (p for p in configuration.providers if p.provider_id == model.provider_id),
            None,
        )
        if (
            provider is None
            or provider.organization_public_id != organization_public_id
        ):
            raise unavailable()
        if (
            not is_runtime_provider_eligible(provider)
            or provider.credential_reference is None
        ):
            raise conflict()

        store = self.credential_store
        if store is None:
            raise credential_unavailable()
        try:
            credential = await store.resolve(
                organization_public_id=organization_public_id,
                provider_id=provider.provider_id,
                credential_reference=provider.credential_reference,
            )
        except CredentialNotFoundError as exc:
            raise conflict() from exc
        except (CredentialStoreError, ModelProviderConfigurationError) as exc:
            raise credential_unavailable() from exc
        if not isinstance(credential, ProviderCredentialSecret):
            raise credential_unavailable()

        try:
            return ResolvedEmbeddingModel(
                model_id=model.model_id,
                provider_id=provider.provider_id,
                provider_type=provider.provider_type,
                provider_model_name=model.provider_model_name,
                embedding_dimension=dimension,
                settings=provider.settings,
                credential=credential,
            )
        except ModelProviderConfigurationError as exc:
            raise unavailable() from exc


def _resolve_model(
    configuration: OrganizationModelProviderConfiguration | None,
    *,
    model_id: ConfiguredModelId | None,
) -> ConfiguredModel:
    if configuration is None:
        if model_id is not None:
            raise NexusError(ErrorCode.NOT_FOUND, NOT_FOUND)
        raise NexusError(ErrorCode.CONFLICT, _NO_DEFAULT)
    selected_id = model_id if model_id is not None else configuration.defaults.embedding
    if selected_id is None:
        raise NexusError(ErrorCode.CONFLICT, _NO_DEFAULT)
    for model in configuration.models:
        if model.model_id == selected_id:
            return model
    if model_id is not None:
        raise NexusError(ErrorCode.NOT_FOUND, NOT_FOUND)
    raise unavailable()


__all__ = ["ResolveEmbeddingModel", "ResolvedEmbeddingModel"]
