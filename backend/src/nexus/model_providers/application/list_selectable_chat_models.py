"""Safe organization-scoped chat-model selection listing."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from nexus.model_providers.application._runtime_model_eligibility import (
    is_runtime_provider_eligible,
    is_streaming_chat_model,
)
from nexus.model_providers.application._shared import load_configuration, unavailable
from nexus.model_providers.domain import (
    ConfiguredModelId,
    ModelProviderConfigurationError,
    ProviderType,
)
from nexus.model_providers.ports import ModelProviderPersistence


@dataclass(frozen=True)
class SelectableChatModel:
    model_id: ConfiguredModelId
    display_name: str
    provider_type: ProviderType
    provider_display_name: str


@dataclass(frozen=True)
class SelectableChatModels:
    items: tuple[SelectableChatModel, ...]
    default_model_id: ConfiguredModelId | None


@dataclass(frozen=True)
class ListSelectableChatModels:
    """List safe model-selection metadata without resolving credentials."""

    persistence: ModelProviderPersistence

    async def execute(
        self,
        *,
        organization_public_id: UUID,
    ) -> SelectableChatModels:
        try:
            configuration = await load_configuration(
                self.persistence,
                organization_public_id=organization_public_id,
            )
        except ModelProviderConfigurationError as exc:
            raise unavailable() from exc

        if configuration is None:
            return SelectableChatModels(items=(), default_model_id=None)

        providers = {
            provider.provider_id: provider for provider in configuration.providers
        }
        items: list[SelectableChatModel] = []
        selectable_ids: set[ConfiguredModelId] = set()
        for model in configuration.models:
            provider = providers.get(model.provider_id)
            if provider is None:
                raise unavailable()
            if (
                not is_streaming_chat_model(model)
                or not is_runtime_provider_eligible(provider)
                or provider.credential_reference is None
            ):
                continue
            items.append(
                SelectableChatModel(
                    model_id=model.model_id,
                    display_name=model.display_name,
                    provider_type=provider.provider_type,
                    provider_display_name=provider.display_name,
                )
            )
            selectable_ids.add(model.model_id)

        configured_default = configuration.defaults.chat
        return SelectableChatModels(
            items=tuple(items),
            default_model_id=(
                configured_default if configured_default in selectable_ids else None
            ),
        )


__all__ = [
    "ListSelectableChatModels",
    "SelectableChatModel",
    "SelectableChatModels",
]
