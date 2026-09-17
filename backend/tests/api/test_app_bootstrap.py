from collections.abc import AsyncIterator
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from nexus.api.dependencies import get_event_publisher
from nexus.config.settings import Settings
from nexus.events import EventEnvelope, EventPublisher, InProcessEventPublisher
from nexus.llm.domain import LLMEvent, LLMRequest, LLMResponse, LLMStartedEvent
from nexus.llm.infrastructure.gateway_factory import UnsupportedLLMGatewayError
from nexus.main import create_app


class FakeLLMGateway:
    async def generate(self, request: LLMRequest) -> LLMResponse:
        del request
        raise NotImplementedError

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        del request
        return _empty_llm_stream()


async def _empty_llm_stream() -> AsyncIterator[LLMEvent]:
    if False:
        yield LLMStartedEvent()


def build_settings(**overrides: object) -> Settings:
    values = {
        "database_url": "postgresql://test:test@localhost:5432/test",
        "redis_url": "redis://localhost:6379/15",
        "cors_allowed_origins": ["https://nexus.example"],
        "otp_hmac_secret": "test-secret-value-with-enough-length",
        "auth_token_secret": "test-auth-token-secret-with-enough-length",
        "refresh_token_secret": "test-refresh-token-secret-with-enough-length",
        **overrides,
    }
    if "debug" in values:
        values["APP_DEBUG"] = values.pop("debug")
    return Settings(_env_file=None, **values)


def test_create_app_returns_configured_fastapi_application() -> None:
    app = create_app(build_settings(app_name="NEXUS Test", debug=True))

    assert isinstance(app, FastAPI)
    assert app.title == "NEXUS Test"
    assert app.debug is True
    assert app.version == "v1"


def test_router_uses_configured_api_prefix() -> None:
    app = create_app(build_settings(api_prefix="/custom/v1"))

    with TestClient(app) as client:
        response = client.get("/custom/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_request_context_remains_registered() -> None:
    app = create_app(build_settings())

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"].startswith("req_")


def test_cors_allows_configured_origin() -> None:
    app = create_app(build_settings())

    with TestClient(app) as client:
        response = client.options(
            "/api/v1/health",
            headers={
                "Origin": "https://nexus.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://nexus.example"


def test_cors_does_not_allow_unconfigured_origin() -> None:
    app = create_app(build_settings())

    with TestClient(app) as client:
        response = client.options(
            "/api/v1/health",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert "access-control-allow-origin" not in response.headers


def test_default_event_publisher_is_application_scoped() -> None:
    app = create_app(build_settings())

    assert isinstance(app.state.event_publisher, InProcessEventPublisher)


def test_llm_gateway_and_use_cases_are_application_scoped() -> None:
    gateway = FakeLLMGateway()
    app = create_app(build_settings(), llm_gateway=gateway)

    assert app.state.llm.gateway is gateway
    assert app.state.llm.generate.gateway is gateway
    assert app.state.llm.stream.gateway is gateway


def test_unsupported_llm_gateway_fails_during_application_composition() -> None:
    with pytest.raises(
        UnsupportedLLMGatewayError,
        match="Unsupported LLM gateway configuration",
    ):
        create_app(build_settings(llm_gateway="unsupported"))


def test_event_publisher_can_be_injected_and_resolved_through_fastapi() -> None:
    class StubPublisher:
        async def publish(self, event: EventEnvelope) -> None:
            del event

    publisher = StubPublisher()
    app = create_app(build_settings(), event_publisher=publisher)

    @app.get("/publisher-test")
    async def publisher_test(
        resolved: Annotated[EventPublisher, Depends(get_event_publisher)],
    ) -> dict[str, bool]:
        return {"same_instance": resolved is publisher}

    with TestClient(app) as client:
        response = client.get("/publisher-test")

    assert response.status_code == 200
    assert response.json() == {"same_instance": True}
