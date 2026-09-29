"""Explicit resolved-target mapping for LiteLLM runtime invocation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import assert_never

from nexus.llm.domain import LLMInvalidRequestError
from nexus.model_providers.domain import (
    AnthropicSettings,
    AzureOpenAISettings,
    GeminiSettings,
    OpenAICompatibleSettings,
    OpenAISettings,
    ProviderType,
    ResolvedChatModel,
)

_INVALID_TARGET = "LLM runtime target is invalid."
_OPENAI_ENDPOINT = "https://api.openai.com/v1"
_ANTHROPIC_ENDPOINT = "https://api.anthropic.com"
_GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com"


class RuntimeClientKind(StrEnum):
    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    HTTP_HANDLER = "http_handler"


@dataclass(frozen=True, slots=True)
class LiteLLMRuntimeMapping:
    """Non-secret provider arguments and secure-client construction inputs."""

    model: str
    custom_llm_provider: str
    endpoint: str
    client_kind: RuntimeClientKind
    api_base: str | None = None
    api_version: str | None = None
    rust: bool | None = None

    def invocation_arguments(self) -> dict[str, object]:
        arguments: dict[str, object] = {
            "model": self.model,
            "custom_llm_provider": self.custom_llm_provider,
        }
        if self.api_base is not None:
            arguments["api_base"] = self.api_base
        if self.api_version is not None:
            arguments["api_version"] = self.api_version
        if self.rust is not None:
            arguments["rust"] = self.rust
        return arguments


def map_runtime_target(target: ResolvedChatModel) -> LiteLLMRuntimeMapping:
    """Map one validated target without revealing its credential."""

    provider_type = target.provider_type
    settings = target.settings
    if provider_type is ProviderType.OPENAI:
        _require_settings(settings, OpenAISettings)
        return LiteLLMRuntimeMapping(
            model=target.provider_model_name,
            custom_llm_provider="openai",
            endpoint=_OPENAI_ENDPOINT,
            client_kind=RuntimeClientKind.OPENAI,
        )
    if provider_type is ProviderType.ANTHROPIC:
        _require_settings(settings, AnthropicSettings)
        return LiteLLMRuntimeMapping(
            model=target.provider_model_name,
            custom_llm_provider="anthropic",
            endpoint=_ANTHROPIC_ENDPOINT,
            api_base=_ANTHROPIC_ENDPOINT,
            client_kind=RuntimeClientKind.HTTP_HANDLER,
            rust=False,
        )
    if provider_type is ProviderType.AZURE_OPENAI:
        azure = _require_settings(settings, AzureOpenAISettings)
        return LiteLLMRuntimeMapping(
            model=target.provider_model_name,
            custom_llm_provider="azure",
            endpoint=azure.endpoint,
            api_base=azure.endpoint,
            api_version=azure.api_version,
            client_kind=RuntimeClientKind.AZURE_OPENAI,
        )
    if provider_type is ProviderType.GEMINI:
        _require_settings(settings, GeminiSettings)
        return LiteLLMRuntimeMapping(
            model=target.provider_model_name,
            custom_llm_provider="gemini",
            endpoint=_GEMINI_ENDPOINT,
            api_base=_GEMINI_ENDPOINT,
            client_kind=RuntimeClientKind.HTTP_HANDLER,
        )
    if provider_type is ProviderType.OPENAI_COMPATIBLE:
        compatible = _require_settings(settings, OpenAICompatibleSettings)
        return LiteLLMRuntimeMapping(
            model=target.provider_model_name,
            custom_llm_provider="openai",
            endpoint=compatible.base_url,
            api_base=compatible.base_url,
            client_kind=RuntimeClientKind.OPENAI,
        )
    assert_never(provider_type)


def _require_settings[SettingsT](
    settings: object,
    expected_type: type[SettingsT],
) -> SettingsT:
    if not isinstance(settings, expected_type):
        raise LLMInvalidRequestError(_INVALID_TARGET)
    return settings


__all__ = [
    "LiteLLMRuntimeMapping",
    "RuntimeClientKind",
    "map_runtime_target",
]
