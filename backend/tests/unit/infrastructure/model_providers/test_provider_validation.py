from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Self

import pytest

from nexus.infrastructure.model_providers import provider_http as http_module
from nexus.infrastructure.model_providers import provider_validation as module
from nexus.infrastructure.model_providers.provider_validation import (
    HttpProviderConfigurationValidator,
)
from nexus.model_providers.domain import (
    AnthropicSettings,
    AzureOpenAISettings,
    GeminiSettings,
    OpenAICompatibleSettings,
    OpenAISettings,
    ProviderCredentialSecret,
    ProviderType,
    ProviderValidationStatus,
)


@pytest.mark.parametrize(
    ("provider_type", "settings", "expected_url", "header_name"),
    [
        (
            ProviderType.OPENAI,
            OpenAISettings(),
            "https://api.openai.com/v1/models",
            "Authorization",
        ),
        (
            ProviderType.ANTHROPIC,
            AnthropicSettings(),
            "https://api.anthropic.com/v1/models?limit=1",
            "x-api-key",
        ),
        (
            ProviderType.GEMINI,
            GeminiSettings(),
            "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
            "x-goog-api-key",
        ),
    ],
)
def test_fixed_provider_validation_requests_use_header_credentials(
    provider_type: ProviderType,
    settings: object,
    expected_url: str,
    header_name: str,
) -> None:
    request = module._validation_request(
        provider_type,
        settings,  # type: ignore[arg-type]
        ProviderCredentialSecret("secret-value"),
    )

    assert request.url == expected_url
    assert request.headers[header_name].endswith("secret-value")
    assert "secret-value" not in request.url


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://account.openai.azure.com",
        "https://account.openai.azure.com/",
    ],
)
def test_azure_path_append_handles_trailing_slash(endpoint: str) -> None:
    request = module._validation_request(
        ProviderType.AZURE_OPENAI,
        AzureOpenAISettings(endpoint=endpoint, api_version="2024-10-21"),
        ProviderCredentialSecret("secret-value"),
    )

    assert request.url == (
        "https://account.openai.azure.com/openai/models?api-version=2024-10-21"
    )
    assert request.headers == {"api-key": "secret-value"}


@pytest.mark.parametrize(
    "base_url",
    ["https://provider.example/v1", "https://provider.example/v1/"],
)
def test_openai_compatible_path_append_preserves_last_segment(base_url: str) -> None:
    request = module._validation_request(
        ProviderType.OPENAI_COMPATIBLE,
        OpenAICompatibleSettings(base_url=base_url),
        ProviderCredentialSecret("secret-value"),
    )

    assert request.url == "https://provider.example/v1/models"


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (200, ProviderValidationStatus.VALID),
        (204, ProviderValidationStatus.VALID),
        (401, ProviderValidationStatus.INVALID_CREDENTIALS),
        (403, ProviderValidationStatus.UNSUPPORTED_CONFIGURATION),
        (404, ProviderValidationStatus.UNSUPPORTED_CONFIGURATION),
        (408, ProviderValidationStatus.UNREACHABLE),
        (425, ProviderValidationStatus.UNREACHABLE),
        (429, ProviderValidationStatus.UNREACHABLE),
        (500, ProviderValidationStatus.UNREACHABLE),
        (503, ProviderValidationStatus.UNREACHABLE),
        (302, ProviderValidationStatus.UNSUPPORTED_CONFIGURATION),
    ],
)
def test_status_classification(status: int, outcome: ProviderValidationStatus) -> None:
    assert module._status_outcome(status) is outcome


@dataclass
class _FakeResponse:
    status: int = 200
    closed: bool = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def close(self) -> None:
        self.closed = True


@dataclass
class _FakeSession:
    constructor_kwargs: dict[str, Any]
    request_kwargs: dict[str, Any] = field(default_factory=dict)
    response: _FakeResponse = field(default_factory=_FakeResponse)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def get(self, url: str, **kwargs: object) -> _FakeResponse:
        self.request_kwargs = {"url": url, **kwargs}
        return self.response


def test_transport_disables_environment_and_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def resolve(*_args: object, **_kwargs: object) -> tuple[object, ...]:
        return ()

    def session_factory(**kwargs: object) -> _FakeSession:
        session = _FakeSession(dict(kwargs))
        captured["session"] = session
        return session

    monkeypatch.setattr(http_module, "resolve_public_addresses", resolve)
    monkeypatch.setattr(http_module.aiohttp, "TCPConnector", lambda **kwargs: kwargs)
    monkeypatch.setattr(http_module.aiohttp, "ClientSession", session_factory)
    validator = HttpProviderConfigurationValidator(timeout_seconds=3)

    outcome = asyncio.run(
        validator.validate(
            provider_type=ProviderType.OPENAI,
            settings=OpenAISettings(),
            secret=ProviderCredentialSecret("secret-value"),
        )
    )

    session = captured["session"]
    assert outcome is ProviderValidationStatus.VALID
    assert session.constructor_kwargs["trust_env"] is False
    assert session.constructor_kwargs["auto_decompress"] is False
    assert session.request_kwargs["allow_redirects"] is False
    assert session.response.closed is True


def test_overall_timeout_includes_dns_resolution() -> None:
    class SlowResolver:
        async def resolve(self, **_kwargs: object) -> tuple[object, ...]:
            await asyncio.sleep(1)
            return ()

    validator = HttpProviderConfigurationValidator(
        timeout_seconds=0.001,
        resolver=SlowResolver(),  # type: ignore[arg-type]
    )

    outcome = asyncio.run(
        validator.validate(
            provider_type=ProviderType.OPENAI,
            settings=OpenAISettings(),
            secret=ProviderCredentialSecret("secret-value"),
        )
    )

    assert outcome is ProviderValidationStatus.UNREACHABLE
