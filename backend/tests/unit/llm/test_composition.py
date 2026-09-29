from __future__ import annotations

from collections.abc import AsyncIterator

from nexus.composition.root import build_llm_composition
from nexus.config.settings import Settings
from nexus.llm.domain import LLMEvent, LLMRequest, LLMResponse, LLMStartedEvent
from nexus.llm.infrastructure.adapters.litellm import LiteLLMRuntimeAdapter
from nexus.model_providers.domain import ResolvedChatModel


class FakeRuntimeGateway:
    async def generate(
        self,
        *,
        request: LLMRequest,
        target: ResolvedChatModel,
    ) -> LLMResponse:
        del request, target
        raise NotImplementedError

    def stream(
        self,
        *,
        request: LLMRequest,
        target: ResolvedChatModel,
    ) -> AsyncIterator[LLMEvent]:
        del request, target
        return _empty_stream()


async def _empty_stream() -> AsyncIterator[LLMEvent]:
    if False:
        yield LLMStartedEvent()


def build_settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/15",
        cors_allowed_origins=["https://nexus.example"],
        otp_hmac_secret="test-secret-value-with-enough-length",
        auth_token_secret="test-auth-token-secret-with-enough-length",
        refresh_token_secret="test-refresh-token-secret-with-enough-length",
        file_upload_context_key=("bmV4dXMtZGV2ZWxvcG1lbnQtdXBsb2FkLWtleS0wMDE"),
        **overrides,
    )


def test_composition_builds_litellm_runtime_gateway() -> None:
    composition = build_llm_composition(build_settings())

    assert isinstance(composition.runtime_gateway, LiteLLMRuntimeAdapter)


def test_composition_uses_injected_runtime_gateway_without_provider_access() -> None:
    runtime_gateway = FakeRuntimeGateway()

    composition = build_llm_composition(
        build_settings(),
        runtime_gateway=runtime_gateway,
    )

    assert composition.runtime_gateway is runtime_gateway


def test_composition_does_not_store_tenant_credentials() -> None:
    composition = build_llm_composition(build_settings())

    assert set(vars(composition)) == {"runtime_gateway"}
