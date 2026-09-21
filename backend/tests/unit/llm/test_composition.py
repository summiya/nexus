from __future__ import annotations

from collections.abc import AsyncIterator

from nexus.composition.root import build_llm_composition
from nexus.config.settings import Settings
from nexus.llm.domain import LLMEvent, LLMRequest, LLMResponse, LLMStartedEvent
from nexus.llm.infrastructure.adapters.litellm import LiteLLMAdapter


class FakeGateway:
    def __bool__(self) -> bool:
        return False

    async def generate(self, request: LLMRequest) -> LLMResponse:
        del request
        raise NotImplementedError

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        del request
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
        **overrides,
    )


def test_composition_builds_litellm_gateway_and_model_policy() -> None:
    composition = build_llm_composition(build_settings())

    assert isinstance(composition.gateway, LiteLLMAdapter)
    assert composition.model_policy.allowed_models == frozenset({"gpt-4o-mini"})


def test_composition_uses_one_injected_gateway_without_provider_access() -> None:
    gateway = FakeGateway()

    composition = build_llm_composition(build_settings(), gateway=gateway)

    assert composition.gateway is gateway


def test_composition_does_not_store_tenant_credentials() -> None:
    composition = build_llm_composition(build_settings(), gateway=FakeGateway())

    assert set(vars(composition)) == {"gateway", "model_policy"}
