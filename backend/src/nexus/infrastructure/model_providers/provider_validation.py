"""HTTP validation adapter for configured model providers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from urllib.parse import urlencode, urlunsplit

import aiohttp

from nexus.infrastructure.model_providers.outbound_endpoint import (
    HostResolver,
    PinnedResolver,
    SystemHostResolver,
    UnsafeProviderEndpointError,
    parse_https_endpoint,
    resolve_public_addresses,
)
from nexus.model_providers.domain import (
    AnthropicSettings,
    AzureOpenAISettings,
    GeminiSettings,
    OpenAICompatibleSettings,
    OpenAISettings,
    ProviderCredentialSecret,
    ProviderSettings,
    ProviderType,
    ProviderValidationStatus,
)

_OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
_ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models?limit=1"
_GEMINI_MODELS_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1"
)


@dataclass(frozen=True, slots=True)
class _ValidationRequest:
    url: str
    headers: dict[str, str]


@dataclass(frozen=True)
class HttpProviderConfigurationValidator:
    """Validate provider authentication with a minimal metadata request."""

    timeout_seconds: float
    resolver: HostResolver = field(default_factory=SystemHostResolver)

    async def validate(
        self,
        *,
        provider_type: ProviderType,
        settings: ProviderSettings,
        secret: ProviderCredentialSecret,
    ) -> ProviderValidationStatus:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                request = _validation_request(provider_type, settings, secret)
                return await self._send(request)
        except UnsafeProviderEndpointError:
            return ProviderValidationStatus.UNSUPPORTED_CONFIGURATION
        except TimeoutError:
            return ProviderValidationStatus.UNREACHABLE
        except (aiohttp.ClientError, OSError):
            return ProviderValidationStatus.UNREACHABLE

    async def _send(
        self,
        request: _ValidationRequest,
    ) -> ProviderValidationStatus:
        parsed = parse_https_endpoint(request.url)
        addresses = await resolve_public_addresses(parsed, resolver=self.resolver)
        hostname = parsed.hostname
        if hostname is None:  # guarded by parse_https_endpoint
            raise UnsafeProviderEndpointError("Provider endpoint is not supported.")
        connector = aiohttp.TCPConnector(
            resolver=PinnedResolver(hostname=hostname, addresses=addresses),
            use_dns_cache=False,
            limit=1,
        )
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        async with (
            aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                trust_env=False,
                auto_decompress=False,
            ) as session,
            session.get(
                request.url,
                headers=request.headers,
                allow_redirects=False,
            ) as response,
        ):
            status = response.status
            response.close()
        return _status_outcome(status)


def _validation_request(
    provider_type: ProviderType,
    settings: ProviderSettings,
    secret: ProviderCredentialSecret,
) -> _ValidationRequest:
    credential = secret.reveal()
    if provider_type is ProviderType.OPENAI and isinstance(settings, OpenAISettings):
        return _ValidationRequest(
            url=_OPENAI_MODELS_URL,
            headers={"Authorization": f"Bearer {credential}"},
        )
    if provider_type is ProviderType.ANTHROPIC and isinstance(
        settings, AnthropicSettings
    ):
        return _ValidationRequest(
            url=_ANTHROPIC_MODELS_URL,
            headers={
                "x-api-key": credential,
                "anthropic-version": "2023-06-01",
            },
        )
    if provider_type is ProviderType.AZURE_OPENAI and isinstance(
        settings, AzureOpenAISettings
    ):
        return _ValidationRequest(
            url=_with_query(
                _append_path(settings.endpoint, "openai/models"),
                {"api-version": settings.api_version},
            ),
            headers={"api-key": credential},
        )
    if provider_type is ProviderType.GEMINI and isinstance(settings, GeminiSettings):
        return _ValidationRequest(
            url=_GEMINI_MODELS_URL,
            headers={"x-goog-api-key": credential},
        )
    if provider_type is ProviderType.OPENAI_COMPATIBLE and isinstance(
        settings, OpenAICompatibleSettings
    ):
        return _ValidationRequest(
            url=_append_path(settings.base_url, "models"),
            headers={"Authorization": f"Bearer {credential}"},
        )
    raise TypeError("Provider settings do not match provider type")


def _append_path(base_url: str, suffix: str) -> str:
    parsed = parse_https_endpoint(base_url)
    path = f"{parsed.path.rstrip('/')}/{suffix.lstrip('/')}"
    return urlunsplit(parsed._replace(path=path))


def _with_query(url: str, query: dict[str, str]) -> str:
    parsed = parse_https_endpoint(url)
    return urlunsplit(parsed._replace(query=urlencode(query)))


def _status_outcome(status: int) -> ProviderValidationStatus:
    if 200 <= status < 300:
        return ProviderValidationStatus.VALID
    if status == 401:
        return ProviderValidationStatus.INVALID_CREDENTIALS
    if status in {408, 425, 429} or 500 <= status < 600:
        return ProviderValidationStatus.UNREACHABLE
    if 400 <= status < 500:
        # In particular, Azure OpenAI 403 may be a network/firewall restriction.
        return ProviderValidationStatus.UNSUPPORTED_CONFIGURATION
    return ProviderValidationStatus.UNSUPPORTED_CONFIGURATION


__all__ = ["HttpProviderConfigurationValidator"]
