"""Bounded HTTP model discovery for supported configured providers."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping, Sized
from dataclasses import dataclass, field

import aiohttp

from nexus.config.litellm import require_local_litellm_metadata
from nexus.infrastructure.model_providers.outbound_endpoint import (
    HostResolver,
    SystemHostResolver,
    UnsafeProviderEndpointError,
)
from nexus.infrastructure.model_providers.provider_http import (
    is_retryable_provider_status,
    pinned_provider_get,
    with_query,
)
from nexus.model_providers.domain import (
    AnthropicSettings,
    AzureOpenAISettings,
    GeminiSettings,
    ModelCandidate,
    ModelCapability,
    ModelType,
    OpenAICompatibleSettings,
    OpenAISettings,
    ProviderCredentialSecret,
    ProviderSettings,
    ProviderType,
)
from nexus.model_providers.ports import (
    ProviderModelDiscoveryAuthenticationError,
    ProviderModelDiscoveryRejectedError,
    ProviderModelDiscoveryUnavailableError,
    ProviderModelDiscoveryUnsupportedError,
)

MAX_DISCOVERY_RESPONSE_BYTES = 1024 * 1024
MAX_DISCOVERY_PAGES = 10
MAX_DISCOVERY_MODELS = 1000
_PAGE_SIZE = 100
_OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
_ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"
_GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_IDENTITY_ENCODING_HEADERS = {"Accept-Encoding": "identity"}

type ModelInfo = Mapping[str, object]
type ModelInfoLookup = Callable[[str, str], ModelInfo | None]


@dataclass(frozen=True)
class HttpProviderModelCatalog:
    """Discover provider models and normalize only trusted classifications."""

    timeout_seconds: float
    resolver: HostResolver = field(default_factory=SystemHostResolver)
    model_info_lookup: ModelInfoLookup = field(default=lambda p, m: _model_info(p, m))

    async def discover(
        self,
        *,
        provider_type: ProviderType,
        settings: ProviderSettings,
        secret: ProviderCredentialSecret,
    ) -> tuple[ModelCandidate, ...]:
        if provider_type in {
            ProviderType.AZURE_OPENAI,
            ProviderType.OPENAI_COMPATIBLE,
        }:
            self._require_matching_unsupported_settings(provider_type, settings)
            raise ProviderModelDiscoveryUnsupportedError(
                "Automatic provider model discovery is unsupported."
            )
        try:
            async with asyncio.timeout(self.timeout_seconds):
                candidates = await self._discover_supported(
                    provider_type=provider_type,
                    settings=settings,
                    secret=secret,
                )
        except (
            ProviderModelDiscoveryAuthenticationError,
            ProviderModelDiscoveryRejectedError,
            ProviderModelDiscoveryUnsupportedError,
        ):
            raise
        except asyncio.CancelledError:
            raise
        except (TimeoutError, aiohttp.ClientError, OSError) as exc:
            raise ProviderModelDiscoveryUnavailableError(
                "Provider model discovery is unavailable."
            ) from exc
        except (
            UnsafeProviderEndpointError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise ProviderModelDiscoveryUnavailableError(
                "Provider model discovery returned an unusable response."
            ) from exc
        return tuple(sorted(candidates, key=lambda item: item.provider_model_name))

    async def _discover_supported(
        self,
        *,
        provider_type: ProviderType,
        settings: ProviderSettings,
        secret: ProviderCredentialSecret,
    ) -> tuple[ModelCandidate, ...]:
        credential = secret.reveal()
        if provider_type is ProviderType.OPENAI and isinstance(
            settings, OpenAISettings
        ):
            payload = await self._get_json(
                _OPENAI_MODELS_URL,
                {"Authorization": f"Bearer {credential}"},
            )
            return self._openai_candidates(payload)
        if provider_type is ProviderType.ANTHROPIC and isinstance(
            settings, AnthropicSettings
        ):
            return await self._anthropic_candidates(credential)
        if provider_type is ProviderType.GEMINI and isinstance(
            settings, GeminiSettings
        ):
            return await self._gemini_candidates(credential)
        raise TypeError("Provider settings do not match provider type")

    async def _get_json(
        self,
        url: str,
        headers: Mapping[str, str],
    ) -> Mapping[str, object]:
        request_headers = dict(headers)
        request_headers.update(_IDENTITY_ENCODING_HEADERS)
        async with pinned_provider_get(
            url=url,
            headers=request_headers,
            resolver=self.resolver,
            timeout_seconds=self.timeout_seconds,
        ) as response:
            self._raise_for_status(response.status)
            encoding = response.headers.get("Content-Encoding", "identity").lower()
            if encoding not in {"", "identity"}:
                raise ValueError("Encoded provider responses are unsupported")
            body = bytearray()
            async for chunk in response.content.iter_chunked(64 * 1024):
                if len(body) + len(chunk) > MAX_DISCOVERY_RESPONSE_BYTES:
                    raise ValueError("Provider response is too large")
                body.extend(chunk)
        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            raise TypeError("Provider response must be an object")
        return parsed

    @staticmethod
    def _raise_for_status(status: int) -> None:
        if 200 <= status < 300:
            return
        if status in {401, 403}:
            raise ProviderModelDiscoveryAuthenticationError(
                "Provider rejected the configured credential or authorization."
            )
        if is_retryable_provider_status(status):
            raise ProviderModelDiscoveryUnavailableError(
                "Provider model discovery is unavailable."
            )
        raise ProviderModelDiscoveryRejectedError(
            "The provider rejected the model discovery request."
        )

    def _openai_candidates(
        self, payload: Mapping[str, object]
    ) -> tuple[ModelCandidate, ...]:
        if payload.get("object") != "list":
            raise ValueError("OpenAI response type is invalid")
        rows = _required_list(payload, "data")
        _check_model_count(rows)
        candidates: dict[str, ModelCandidate] = {}
        for row in rows:
            model = _required_mapping(row)
            if model.get("object") != "model":
                raise ValueError("OpenAI model type is invalid")
            model_id = _required_string(model, "id")
            info = self.model_info_lookup("openai", model_id)
            candidate = _candidate_from_model_info(
                provider_model_name=model_id,
                display_name=model_id,
                info=info,
                streaming_from_provider=False,
            )
            if candidate is not None:
                candidates[model_id] = candidate
        return tuple(candidates.values())

    async def _anthropic_candidates(
        self, credential: str
    ) -> tuple[ModelCandidate, ...]:
        candidates: dict[str, ModelCandidate] = {}
        after_id: str | None = None
        discovered_rows = 0
        for _page in range(MAX_DISCOVERY_PAGES):
            query = {"limit": str(_PAGE_SIZE)}
            if after_id is not None:
                query["after_id"] = after_id
            payload = await self._get_json(
                with_query(_ANTHROPIC_MODELS_URL, query),
                {
                    "x-api-key": credential,
                    "anthropic-version": "2023-06-01",
                },
            )
            rows = _required_list(payload, "data")
            discovered_rows += len(rows)
            _check_model_count(range(discovered_rows))
            for row_value in rows:
                row = _required_mapping(row_value)
                if row.get("type") != "model":
                    raise ValueError("Anthropic response type is invalid")
                model_id = _required_string(row, "id")
                display_name = _required_string(row, "display_name")
                info = self.model_info_lookup("anthropic", model_id)
                candidate = _candidate_from_model_info(
                    provider_model_name=model_id,
                    display_name=display_name,
                    info=info,
                    streaming_from_provider=True,
                    provider_capabilities=_anthropic_capabilities(row),
                )
                if candidate is not None:
                    candidates[model_id] = candidate
            has_more = payload.get("has_more")
            if type(has_more) is not bool:
                raise ValueError("Anthropic pagination is invalid")
            if not has_more:
                return tuple(candidates.values())
            after_id = _required_string(payload, "last_id")
        raise ValueError("Anthropic pagination limit exceeded")

    async def _gemini_candidates(self, credential: str) -> tuple[ModelCandidate, ...]:
        candidates: dict[str, ModelCandidate] = {}
        page_token: str | None = None
        discovered_rows = 0
        for _page in range(MAX_DISCOVERY_PAGES):
            query = {"pageSize": str(_PAGE_SIZE)}
            if page_token is not None:
                query["pageToken"] = page_token
            payload = await self._get_json(
                with_query(_GEMINI_MODELS_URL, query),
                {"x-goog-api-key": credential},
            )
            rows = _required_list(payload, "models")
            discovered_rows += len(rows)
            _check_model_count(range(discovered_rows))
            for row_value in rows:
                row = _required_mapping(row_value)
                provider_model_name = _gemini_provider_model_name(row)
                if provider_model_name is None:
                    continue
                display_name = _required_string(row, "displayName")
                methods = _required_string_list(row, "supportedGenerationMethods")
                info = self.model_info_lookup("gemini", provider_model_name)
                candidate = _gemini_candidate(
                    provider_model_name=provider_model_name,
                    display_name=display_name,
                    methods=methods,
                    info=info,
                )
                if candidate is not None:
                    candidates[provider_model_name] = candidate
            next_token = payload.get("nextPageToken")
            if next_token is None:
                return tuple(candidates.values())
            if not isinstance(next_token, str) or not next_token:
                raise ValueError("Gemini pagination is invalid")
            page_token = next_token
        raise ValueError("Gemini pagination limit exceeded")

    @staticmethod
    def _require_matching_unsupported_settings(
        provider_type: ProviderType,
        settings: ProviderSettings,
    ) -> None:
        if provider_type is ProviderType.AZURE_OPENAI and isinstance(
            settings, AzureOpenAISettings
        ):
            return
        if provider_type is ProviderType.OPENAI_COMPATIBLE and isinstance(
            settings, OpenAICompatibleSettings
        ):
            return
        raise TypeError("Provider settings do not match provider type")


def _model_info(provider: str, model: str) -> ModelInfo | None:
    require_local_litellm_metadata()
    from litellm import get_model_info

    try:
        return get_model_info(model=model, custom_llm_provider=provider)
    except Exception:  # noqa: BLE001 - LiteLLM raises plain Exception when unmapped
        return None


def _candidate_from_model_info(
    *,
    provider_model_name: str,
    display_name: str,
    info: ModelInfo | None,
    streaming_from_provider: bool,
    provider_capabilities: frozenset[ModelCapability] = frozenset(),
) -> ModelCandidate | None:
    if info is None:
        return None
    mode = info.get("mode")
    if mode == "chat":
        model_type = ModelType.CHAT
    elif mode == "embedding":
        model_type = ModelType.EMBEDDING
    elif mode in {"rerank", "reranker"}:
        model_type = ModelType.RERANKER
    else:
        return None
    capabilities: set[ModelCapability] = set()
    dimension: int | None = None
    if model_type is ModelType.CHAT:
        capabilities.update(provider_capabilities)
        parameters = info.get("supported_openai_params")
        if streaming_from_provider or (
            isinstance(parameters, list) and "stream" in parameters
        ):
            capabilities.add(ModelCapability.STREAMING)
        if info.get("supports_function_calling") is True:
            capabilities.add(ModelCapability.TOOLS)
        if info.get("supports_vision") is True:
            capabilities.add(ModelCapability.VISION)
        if info.get("supports_response_schema") is True:
            capabilities.add(ModelCapability.STRUCTURED_OUTPUT)
    elif model_type is ModelType.EMBEDDING:
        value = info.get("output_vector_size")
        if type(value) is int and value > 0:
            dimension = value
    return ModelCandidate(
        provider_model_name=provider_model_name,
        display_name=display_name,
        model_type=model_type,
        capabilities=frozenset(capabilities),
        embedding_dimension=dimension,
    )


def _gemini_provider_model_name(row: Mapping[str, object]) -> str | None:
    base_model_id = row.get("baseModelId")
    if (
        isinstance(base_model_id, str)
        and base_model_id
        and base_model_id == base_model_id.strip()
        and not base_model_id.startswith("models/")
    ):
        return base_model_id

    resource_name = row.get("name")
    if not isinstance(resource_name, str) or not resource_name.startswith("models/"):
        return None
    model_id = resource_name.removeprefix("models/")
    if not model_id or model_id != model_id.strip() or "/" in model_id:
        return None
    return model_id


def _gemini_candidate(
    *,
    provider_model_name: str,
    display_name: str,
    methods: tuple[str, ...],
    info: ModelInfo | None,
) -> ModelCandidate | None:
    if info is None:
        return None
    mode = info.get("mode")
    if "generateContent" in methods and mode == "chat":
        return _candidate_from_model_info(
            provider_model_name=provider_model_name,
            display_name=display_name,
            info=info,
            streaming_from_provider=True,
        )
    if {"embedContent", "batchEmbedContents"}.intersection(
        methods
    ) and mode == "embedding":
        return _candidate_from_model_info(
            provider_model_name=provider_model_name,
            display_name=display_name,
            info=info,
            streaming_from_provider=False,
        )
    return None


def _anthropic_capabilities(row: Mapping[str, object]) -> frozenset[ModelCapability]:
    raw = row.get("capabilities")
    if raw is None:
        return frozenset()
    capabilities = _required_mapping(raw)
    result: set[ModelCapability] = set()
    if _capability_supported(capabilities, "image_input"):
        result.add(ModelCapability.VISION)
    if _capability_supported(capabilities, "structured_outputs"):
        result.add(ModelCapability.STRUCTURED_OUTPUT)
    return frozenset(result)


def _capability_supported(capabilities: Mapping[str, object], name: str) -> bool:
    value = capabilities.get(name)
    return isinstance(value, dict) and value.get("supported") is True


def _required_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise TypeError("Provider response item is invalid")
    return value


def _required_list(payload: Mapping[str, object], name: str) -> list[object]:
    value = payload.get(name)
    if not isinstance(value, list):
        raise TypeError("Provider response list is invalid")
    return value


def _required_string(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("Provider response field is invalid")
    return value


def _required_string_list(payload: Mapping[str, object], name: str) -> tuple[str, ...]:
    values = _required_list(payload, name)
    if any(not isinstance(value, str) for value in values):
        raise ValueError("Provider response string list is invalid")
    return tuple(values)  # type: ignore[arg-type]


def _check_model_count(values: Sized) -> None:
    if len(values) > MAX_DISCOVERY_MODELS:
        raise ValueError("Provider model count limit exceeded")


__all__ = [
    "MAX_DISCOVERY_MODELS",
    "MAX_DISCOVERY_PAGES",
    "MAX_DISCOVERY_RESPONSE_BYTES",
    "HttpProviderModelCatalog",
]
