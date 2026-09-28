"""Supported model-provider catalog sourced from backend domain contracts."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from nexus.authorization import PermissionChecker, PermissionCheckError
from nexus.errors import ErrorCode, NexusError
from nexus.model_providers.domain import (
    ProviderType,
    provider_required_setting_names,
)

_READ_PERMISSION = "model_providers.read"


@dataclass(frozen=True)
class ProviderCatalogItem:
    provider_type: ProviderType
    display_name: str
    required_settings: tuple[str, ...]


_DISPLAY_NAMES = {
    ProviderType.OPENAI: "OpenAI",
    ProviderType.ANTHROPIC: "Anthropic",
    ProviderType.AZURE_OPENAI: "Azure OpenAI",
    ProviderType.GEMINI: "Gemini",
    ProviderType.OPENAI_COMPATIBLE: "OpenAI-compatible",
}

_CATALOG = tuple(
    ProviderCatalogItem(
        provider_type=provider_type,
        display_name=_DISPLAY_NAMES[provider_type],
        required_settings=provider_required_setting_names(provider_type),
    )
    for provider_type in ProviderType
)


@dataclass(frozen=True)
class ListProviderCatalog:
    permission_checker: PermissionChecker

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
    ) -> tuple[ProviderCatalogItem, ...]:
        try:
            allowed = await self.permission_checker.has_permission(
                organization_public_id=organization_public_id,
                user_public_id=user_public_id,
                permission_key=_READ_PERMISSION,
            )
        except PermissionCheckError as exc:
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "Authorization is temporarily unavailable.",
                retryable=True,
            ) from exc
        if not allowed:
            raise NexusError(
                ErrorCode.FORBIDDEN,
                "You are not allowed to perform this action.",
            )
        return _CATALOG


__all__ = ["ListProviderCatalog", "ProviderCatalogItem"]
