"""Supported model-provider catalog sourced from backend domain contracts."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from nexus.authorization import PermissionChecker, PermissionCheckError
from nexus.errors import ErrorCode, NexusError
from nexus.model_providers.domain import ProviderType

_READ_PERMISSION = "model_providers.read"


@dataclass(frozen=True)
class ProviderCatalogItem:
    provider_type: ProviderType
    display_name: str
    required_settings: tuple[str, ...]


_CATALOG = (
    ProviderCatalogItem(ProviderType.OPENAI, "OpenAI", ()),
    ProviderCatalogItem(ProviderType.ANTHROPIC, "Anthropic", ()),
    ProviderCatalogItem(
        ProviderType.AZURE_OPENAI,
        "Azure OpenAI",
        ("endpoint", "api_version"),
    ),
    ProviderCatalogItem(ProviderType.GEMINI, "Gemini", ()),
    ProviderCatalogItem(
        ProviderType.OPENAI_COMPATIBLE,
        "OpenAI-compatible",
        ("base_url",),
    ),
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
