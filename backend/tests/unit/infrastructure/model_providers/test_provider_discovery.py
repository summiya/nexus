from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest

from nexus.infrastructure.model_providers import provider_discovery as module
from nexus.infrastructure.model_providers.provider_discovery import (
    MAX_DISCOVERY_RESPONSE_BYTES,
    HttpProviderModelCatalog,
)
from nexus.model_providers.domain import (
    AzureOpenAISettings,
    GeminiSettings,
    ModelCapability,
    ModelType,
    OpenAICompatibleSettings,
    OpenAISettings,
    ProviderCredentialSecret,
    ProviderType,
)
from nexus.model_providers.ports import (
    ProviderModelDiscoveryAuthenticationError,
    ProviderModelDiscoveryRejectedError,
    ProviderModelDiscoveryUnavailableError,
    ProviderModelDiscoveryUnsupportedError,
)


def _info(
    mode: str,
    *,
    stream: bool = False,
    vision: bool = False,
    tools: bool = False,
    structured: bool = False,
    dimension: int | None = None,
) -> Mapping[str, object]:
    return {
        "mode": mode,
        "supported_openai_params": ["stream"] if stream else [],
        "supports_vision": vision,
        "supports_function_calling": tools,
        "supports_response_schema": structured,
        "output_vector_size": dimension,
    }


def test_pinned_litellm_metadata_classifies_representative_provider_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")

    openai_info = module._model_info("openai", "gpt-4o-mini")
    anthropic_info = module._model_info("anthropic", "claude-sonnet-4-20250514")
    gemini_info = module._model_info("gemini", "gemini-2.5-flash")

    assert openai_info is not None and openai_info["mode"] == "chat"
    assert anthropic_info is not None and anthropic_info["mode"] == "chat"
    assert gemini_info is not None and gemini_info["mode"] == "chat"


def test_openai_uses_explicit_provider_metadata_and_stream_signal() -> None:
    calls: list[tuple[str, str]] = []

    def lookup(provider: str, model: str) -> Mapping[str, object] | None:
        calls.append((provider, model))
        if model == "known-chat":
            return _info("chat", stream=True, tools=True)
        if model == "known-embedding":
            return _info("embedding", dimension=1536)
        return None

    catalog = HttpProviderModelCatalog(timeout_seconds=1, model_info_lookup=lookup)
    candidates = catalog._openai_candidates(
        {
            "object": "list",
            "data": [
                {"object": "model", "id": "known-chat"},
                {"object": "model", "id": "known-embedding"},
                {"object": "model", "id": "unknown"},
            ],
        }
    )

    assert calls == [
        ("openai", "known-chat"),
        ("openai", "known-embedding"),
        ("openai", "unknown"),
    ]
    assert [candidate.model_type for candidate in candidates] == [
        ModelType.CHAT,
        ModelType.EMBEDDING,
    ]
    assert candidates[0].capabilities == frozenset(
        {ModelCapability.STREAMING, ModelCapability.TOOLS}
    )
    assert candidates[1].embedding_dimension == 1536


def test_openai_chat_without_stream_metadata_does_not_gain_streaming() -> None:
    catalog = HttpProviderModelCatalog(
        timeout_seconds=1,
        model_info_lookup=lambda _provider, _model: _info("chat"),
    )

    candidate = catalog._openai_candidates(
        {"object": "list", "data": [{"object": "model", "id": "chat-model"}]}
    )[0]

    assert ModelCapability.STREAMING not in candidate.capabilities


def test_openai_discovery_uses_exact_request_and_header_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Mapping[str, str]]] = []

    async def get_json(
        _self: HttpProviderModelCatalog,
        url: str,
        headers: Mapping[str, str],
    ) -> Mapping[str, object]:
        calls.append((url, headers))
        return {
            "object": "list",
            "data": [{"object": "model", "id": "known-chat"}],
        }

    monkeypatch.setattr(HttpProviderModelCatalog, "_get_json", get_json)
    catalog = HttpProviderModelCatalog(
        timeout_seconds=1,
        model_info_lookup=lambda _provider, _model: _info("chat", stream=True),
    )

    asyncio.run(
        catalog.discover(
            provider_type=ProviderType.OPENAI,
            settings=OpenAISettings(),
            secret=ProviderCredentialSecret("secret-value"),
        )
    )

    assert calls == [
        (
            "https://api.openai.com/v1/models",
            {"Authorization": "Bearer secret-value"},
        )
    ]
    assert "secret-value" not in calls[0][0]


def test_anthropic_uses_explicit_provider_and_documented_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def lookup(provider: str, model: str) -> Mapping[str, object] | None:
        calls.append((provider, model))
        return _info("chat", tools=True)

    requests: list[tuple[str, Mapping[str, str]]] = []

    async def get_json(
        _self: HttpProviderModelCatalog,
        url: str,
        headers: Mapping[str, str],
    ) -> Mapping[str, object]:
        requests.append((url, headers))
        return {
            "data": [
                {
                    "type": "model",
                    "id": "claude-test",
                    "display_name": "Claude Test",
                    "capabilities": {
                        "image_input": {"supported": True},
                        "structured_outputs": {"supported": True},
                    },
                }
            ],
            "has_more": False,
            "last_id": "claude-test",
        }

    monkeypatch.setattr(HttpProviderModelCatalog, "_get_json", get_json)
    catalog = HttpProviderModelCatalog(timeout_seconds=1, model_info_lookup=lookup)
    candidates = asyncio.run(catalog._anthropic_candidates("credential"))

    assert calls == [("anthropic", "claude-test")]
    assert requests == [
        (
            "https://api.anthropic.com/v1/models?limit=100",
            {
                "x-api-key": "credential",
                "anthropic-version": "2023-06-01",
            },
        )
    ]
    assert "credential" not in requests[0][0]
    assert candidates[0].capabilities == frozenset(
        {
            ModelCapability.STREAMING,
            ModelCapability.TOOLS,
            ModelCapability.VISION,
            ModelCapability.STRUCTURED_OUTPUT,
        }
    )


def test_gemini_requires_base_id_provider_method_and_litellm_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def lookup(provider: str, model: str) -> Mapping[str, object] | None:
        calls.append((provider, model))
        return {
            "gemini-chat": _info("chat", vision=True),
            "gemini-embed": _info("embedding", dimension=768),
            "gemini-image": _info("image_generation"),
        }.get(model)

    payload = {
        "models": [
            {
                "name": "models/gemini-chat",
                "displayName": "Gemini Chat",
                "supportedGenerationMethods": ["generateContent"],
            },
            {
                "name": "models/gemini-embed",
                "baseModelId": "gemini-embed",
                "displayName": "Gemini Embed",
                "supportedGenerationMethods": ["embedContent"],
            },
            {
                "name": "models/gemini-image",
                "baseModelId": None,
                "displayName": "Gemini Image",
                "supportedGenerationMethods": ["generateContent"],
            },
            {
                "name": "gemini-without-resource-prefix",
                "displayName": "Malformed resource",
                "supportedGenerationMethods": ["generateContent"],
            },
        ]
    }

    requests: list[tuple[str, Mapping[str, str]]] = []

    async def get_json(
        _self: HttpProviderModelCatalog,
        url: str,
        headers: Mapping[str, str],
    ) -> Mapping[str, object]:
        requests.append((url, headers))
        return payload

    monkeypatch.setattr(HttpProviderModelCatalog, "_get_json", get_json)
    catalog = HttpProviderModelCatalog(timeout_seconds=1, model_info_lookup=lookup)
    candidates = asyncio.run(
        catalog.discover(
            provider_type=ProviderType.GEMINI,
            settings=GeminiSettings(),
            secret=ProviderCredentialSecret("secret"),
        )
    )

    assert [candidate.provider_model_name for candidate in candidates] == [
        "gemini-chat",
        "gemini-embed",
    ]
    assert all(
        not item.provider_model_name.startswith("models/") for item in candidates
    )
    assert candidates[0].model_type is ModelType.CHAT
    assert ModelCapability.STREAMING in candidates[0].capabilities
    assert candidates[1].model_type is ModelType.EMBEDDING
    assert calls == [
        ("gemini", "gemini-chat"),
        ("gemini", "gemini-embed"),
        ("gemini", "gemini-image"),
    ]
    assert requests == [
        (
            "https://generativelanguage.googleapis.com/v1beta/models?pageSize=100",
            {"x-goog-api-key": "secret"},
        )
    ]
    assert "secret" not in requests[0][0]


def test_model_count_limit_applies_to_unclassified_provider_rows() -> None:
    catalog = HttpProviderModelCatalog(
        timeout_seconds=1,
        model_info_lookup=lambda _provider, _model: None,
    )

    with pytest.raises(ValueError):
        catalog._openai_candidates(
            {
                "object": "list",
                "data": [
                    {"object": "model", "id": f"unknown-{index}"}
                    for index in range(module.MAX_DISCOVERY_MODELS + 1)
                ],
            }
        )


@pytest.mark.parametrize(
    ("provider_type", "settings"),
    [
        (
            ProviderType.AZURE_OPENAI,
            AzureOpenAISettings(
                endpoint="https://azure.example", api_version="2024-10-21"
            ),
        ),
        (
            ProviderType.OPENAI_COMPATIBLE,
            OpenAICompatibleSettings(base_url="https://compatible.example/v1"),
        ),
    ],
)
def test_unsupported_providers_do_not_make_http_requests(
    provider_type: ProviderType,
    settings: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unexpected(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("HTTP must not be called")

    monkeypatch.setattr(HttpProviderModelCatalog, "_get_json", unexpected)
    catalog = HttpProviderModelCatalog(timeout_seconds=1)

    with pytest.raises(ProviderModelDiscoveryUnsupportedError):
        asyncio.run(
            catalog.discover(
                provider_type=provider_type,
                settings=settings,  # type: ignore[arg-type]
                secret=ProviderCredentialSecret("secret"),
            )
        )


@dataclass
class FakeContent:
    chunks: tuple[bytes, ...]

    async def iter_chunked(self, _size: int) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk


@dataclass
class FakeResponse:
    chunks: tuple[bytes, ...]
    status: int = 200
    headers: dict[str, str] | None = None

    def __post_init__(self) -> None:
        self.content = FakeContent(self.chunks)
        if self.headers is None:
            self.headers = {}


def test_discovery_requests_identity_encoding_and_accepts_exact_byte_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_headers: Mapping[str, str] | None = None
    padding = "x" * (MAX_DISCOVERY_RESPONSE_BYTES - len(b'{"padding":""}'))
    body = json.dumps({"padding": padding}, separators=(",", ":")).encode()
    assert len(body) == MAX_DISCOVERY_RESPONSE_BYTES

    @asynccontextmanager
    async def fake_get(**kwargs: object) -> AsyncIterator[FakeResponse]:
        nonlocal captured_headers
        captured_headers = kwargs["headers"]  # type: ignore[assignment]
        yield FakeResponse((body,))

    monkeypatch.setattr(module, "pinned_provider_get", fake_get)
    catalog = HttpProviderModelCatalog(timeout_seconds=1)

    result = asyncio.run(catalog._get_json("https://example.com/models", {}))

    assert result["padding"] == padding
    assert captured_headers == {"Accept-Encoding": "identity"}


@pytest.mark.parametrize(
    ("chunks", "headers"),
    [
        ((b"x" * MAX_DISCOVERY_RESPONSE_BYTES, b"x"), {}),
        ((b"compressed",), {"Content-Encoding": "gzip"}),
    ],
)
def test_oversized_or_encoded_body_fails_safely(
    chunks: tuple[bytes, ...],
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @asynccontextmanager
    async def fake_get(**_kwargs: object) -> AsyncIterator[FakeResponse]:
        yield FakeResponse(chunks, headers=headers)

    monkeypatch.setattr(module, "pinned_provider_get", fake_get)
    catalog = HttpProviderModelCatalog(timeout_seconds=1)

    with pytest.raises(ValueError):
        asyncio.run(catalog._get_json("https://example.com/models", {}))


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (400, ProviderModelDiscoveryRejectedError),
        (401, ProviderModelDiscoveryAuthenticationError),
        (403, ProviderModelDiscoveryAuthenticationError),
        (404, ProviderModelDiscoveryRejectedError),
        (408, ProviderModelDiscoveryUnavailableError),
        (425, ProviderModelDiscoveryUnavailableError),
        (429, ProviderModelDiscoveryUnavailableError),
        (500, ProviderModelDiscoveryUnavailableError),
    ],
)
def test_supported_provider_http_errors_never_become_discovery_unsupported(
    status: int,
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        HttpProviderModelCatalog._raise_for_status(status)


def test_success_status_is_accepted() -> None:
    HttpProviderModelCatalog._raise_for_status(200)


def test_anthropic_paginates_with_after_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[str] = []
    pages = [
        {
            "data": [{"type": "model", "id": "claude-a", "display_name": "Claude A"}],
            "has_more": True,
            "last_id": "claude-a",
        },
        {
            "data": [{"type": "model", "id": "claude-b", "display_name": "Claude B"}],
            "has_more": False,
            "last_id": "claude-b",
        },
    ]

    async def get_json(
        _self: HttpProviderModelCatalog,
        url: str,
        _headers: Mapping[str, str],
    ) -> Mapping[str, object]:
        requests.append(url)
        return pages[len(requests) - 1]

    monkeypatch.setattr(HttpProviderModelCatalog, "_get_json", get_json)
    catalog = HttpProviderModelCatalog(
        timeout_seconds=1,
        model_info_lookup=lambda _provider, _model: _info("chat"),
    )

    candidates = asyncio.run(catalog._anthropic_candidates("credential"))

    assert [item.provider_model_name for item in candidates] == [
        "claude-a",
        "claude-b",
    ]
    assert requests == [
        "https://api.anthropic.com/v1/models?limit=100",
        "https://api.anthropic.com/v1/models?limit=100&after_id=claude-a",
    ]


def test_gemini_paginates_and_normalizes_foundation_model_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[str] = []
    pages = [
        {
            "models": [
                {
                    "name": "models/gemini-foundation",
                    "displayName": "Gemini Foundation",
                    "supportedGenerationMethods": ["generateContent"],
                }
            ],
            "nextPageToken": "page-2",
        },
        {
            "models": [
                {
                    "name": "models/gemini-embed-resource",
                    "baseModelId": "gemini-embed",
                    "displayName": "Gemini Embed",
                    "supportedGenerationMethods": ["embedContent"],
                },
                {
                    "name": "not-a-model-resource",
                    "displayName": "Malformed",
                    "supportedGenerationMethods": ["generateContent"],
                },
            ]
        },
    ]

    def lookup(_provider: str, model: str) -> Mapping[str, object] | None:
        return {
            "gemini-foundation": _info("chat"),
            "gemini-embed": _info("embedding", dimension=768),
        }.get(model)

    async def get_json(
        _self: HttpProviderModelCatalog,
        url: str,
        _headers: Mapping[str, str],
    ) -> Mapping[str, object]:
        requests.append(url)
        return pages[len(requests) - 1]

    monkeypatch.setattr(HttpProviderModelCatalog, "_get_json", get_json)
    catalog = HttpProviderModelCatalog(timeout_seconds=1, model_info_lookup=lookup)

    candidates = asyncio.run(catalog._gemini_candidates("credential"))

    assert [item.provider_model_name for item in candidates] == [
        "gemini-foundation",
        "gemini-embed",
    ]
    assert all(
        not item.provider_model_name.startswith("models/") for item in candidates
    )
    assert requests == [
        "https://generativelanguage.googleapis.com/v1beta/models?pageSize=100",
        (
            "https://generativelanguage.googleapis.com/v1beta/models?pageSize=100"
            "&pageToken=page-2"
        ),
    ]


def test_anthropic_aggregate_model_limit_is_enforced_across_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def get_json(
        _self: HttpProviderModelCatalog,
        _url: str,
        _headers: Mapping[str, str],
    ) -> Mapping[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "data": [
                    {"type": "model", "id": f"model-{i}", "display_name": f"Model {i}"}
                    for i in range(module.MAX_DISCOVERY_MODELS)
                ],
                "has_more": True,
                "last_id": "model-999",
            }
        return {
            "data": [{"type": "model", "id": "overflow", "display_name": "Overflow"}],
            "has_more": False,
            "last_id": "overflow",
        }

    monkeypatch.setattr(HttpProviderModelCatalog, "_get_json", get_json)
    catalog = HttpProviderModelCatalog(
        timeout_seconds=1,
        model_info_lookup=lambda _provider, _model: None,
    )

    with pytest.raises(ValueError, match="model count limit"):
        asyncio.run(catalog._anthropic_candidates("credential"))

    assert calls == 2


def test_anthropic_page_limit_is_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def get_json(
        _self: HttpProviderModelCatalog,
        _url: str,
        _headers: Mapping[str, str],
    ) -> Mapping[str, object]:
        nonlocal calls
        calls += 1
        return {
            "data": [],
            "has_more": True,
            "last_id": f"cursor-{calls}",
        }

    monkeypatch.setattr(HttpProviderModelCatalog, "_get_json", get_json)
    catalog = HttpProviderModelCatalog(timeout_seconds=1)

    with pytest.raises(ValueError, match="pagination limit"):
        asyncio.run(catalog._anthropic_candidates("credential"))

    assert calls == module.MAX_DISCOVERY_PAGES


def test_later_page_failure_returns_no_partial_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def get_json(
        _self: HttpProviderModelCatalog,
        _url: str,
        _headers: Mapping[str, str],
    ) -> Mapping[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "data": [
                    {"type": "model", "id": "claude-a", "display_name": "Claude A"}
                ],
                "has_more": True,
                "last_id": "claude-a",
            }
        raise ValueError("malformed second page")

    monkeypatch.setattr(HttpProviderModelCatalog, "_get_json", get_json)
    catalog = HttpProviderModelCatalog(
        timeout_seconds=1,
        model_info_lookup=lambda _provider, _model: _info("chat"),
    )

    with pytest.raises(ValueError, match="malformed second page"):
        asyncio.run(catalog._anthropic_candidates("credential"))

    assert calls == 2


def test_malformed_anthropic_pagination_fails_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def get_json(
        _self: HttpProviderModelCatalog,
        _url: str,
        _headers: Mapping[str, str],
    ) -> Mapping[str, object]:
        return {"data": [], "has_more": "yes", "last_id": "cursor"}

    monkeypatch.setattr(HttpProviderModelCatalog, "_get_json", get_json)
    catalog = HttpProviderModelCatalog(timeout_seconds=1)

    with pytest.raises(ValueError, match="pagination is invalid"):
        asyncio.run(catalog._anthropic_candidates("credential"))
