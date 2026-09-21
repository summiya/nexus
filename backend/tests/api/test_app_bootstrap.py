from collections.abc import AsyncIterator
from typing import Annotated
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from nexus.api.dependencies import get_event_publisher
from nexus.authentication.tokens import AuthTokenContext
from nexus.config.settings import Settings
from nexus.errors import NexusError
from nexus.events import EventEnvelope, EventPublisher, InProcessEventPublisher
from nexus.infrastructure.mailer import EmailDeliveryError, EmailMessage
from nexus.infrastructure.rate_limit import RedisRateLimiter
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


class AllowAllRateLimiter:
    def allow(self, *, key: str, limit: int, window_seconds: int) -> bool:
        del key, limit, window_seconds
        return True


class TrackingRateLimiter(AllowAllRateLimiter):
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class StubEmailProvider:
    def send(self, message: EmailMessage) -> None:
        del message


class TrackingDatabase:
    def __init__(self) -> None:
        self.disposed = False
        self.session_factory = lambda: None

    def dispose(self) -> None:
        self.disposed = True


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


def create_test_app(settings: Settings, **overrides: object) -> FastAPI:
    return create_app(
        settings,
        rate_limiter=AllowAllRateLimiter(),
        email_provider=StubEmailProvider(),
        **overrides,
    )


def test_create_app_returns_configured_fastapi_application() -> None:
    app = create_test_app(build_settings(app_name="NEXUS Test", debug=True))

    with TestClient(app):
        assert isinstance(app, FastAPI)
        assert app.title == "NEXUS Test"
        assert app.debug is True
        assert app.version == "v1"


def test_router_uses_configured_api_prefix() -> None:
    app = create_test_app(build_settings(api_prefix="/custom/v1"))

    with TestClient(app) as client:
        response = client.get("/custom/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_request_context_remains_registered() -> None:
    app = create_test_app(build_settings())

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"].startswith("req_")


def test_cors_allows_configured_origin() -> None:
    app = create_test_app(build_settings())

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
    app = create_test_app(build_settings())

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
    app = create_test_app(build_settings())

    with TestClient(app):
        assert isinstance(
            app.state.container.event_publisher,
            InProcessEventPublisher,
        )


def test_llm_gateway_and_use_cases_are_application_scoped() -> None:
    gateway = FakeLLMGateway()
    app = create_test_app(build_settings(), llm_gateway=gateway)

    with TestClient(app):
        assert app.state.container.llm.gateway is gateway
        assert app.state.container.llm.generate.gateway is gateway
        assert app.state.container.llm.stream.gateway is gateway


def test_unsupported_llm_gateway_fails_during_application_composition() -> None:
    with pytest.raises(
        UnsupportedLLMGatewayError,
        match="Unsupported LLM gateway configuration",
    ):
        create_test_app(build_settings(llm_gateway="unsupported"))


def test_event_publisher_can_be_injected_and_resolved_through_fastapi() -> None:
    class StubPublisher:
        async def publish(self, event: EventEnvelope) -> None:
            del event

    publisher = StubPublisher()
    app = create_test_app(build_settings(), event_publisher=publisher)

    @app.get("/publisher-test")
    async def publisher_test(
        resolved: Annotated[EventPublisher, Depends(get_event_publisher)],
    ) -> dict[str, bool]:
        return {"same_instance": resolved is publisher}

    with TestClient(app) as client:
        response = client.get("/publisher-test")

    assert response.status_code == 200
    assert response.json() == {"same_instance": True}


def test_two_apps_keep_database_redis_and_token_configuration_isolated() -> None:
    settings_a = build_settings(
        database_url="postgresql://test:test@localhost:5432/nexus_a",
        redis_url="redis://localhost:6379/1",
        auth_token_secret="a" * 32,
    )
    settings_b = build_settings(
        database_url="postgresql://test:test@localhost:5432/nexus_b",
        redis_url="redis://localhost:6379/2",
        auth_token_secret="b" * 32,
    )
    app_a = create_app(settings_a, email_provider=StubEmailProvider())
    app_b = create_app(settings_b, email_provider=StubEmailProvider())

    context = AuthTokenContext(
        user_public_id=uuid4(),
        organization_public_id=uuid4(),
        session_public_id=uuid4(),
    )
    token_a = (
        app_a.state.container.authentication.access_token_service.issue_access_token(
            context
        )
    )

    with TestClient(app_a), TestClient(app_b):
        assert app_a.state.container.settings is settings_a
        assert app_b.state.container.settings is settings_b
        assert app_a.state.container.database.engine.url.database == "nexus_a"
        assert app_b.state.container.database.engine.url.database == "nexus_b"

        limiter_a = app_a.state.container.authentication.rate_limiter
        limiter_b = app_b.state.container.authentication.rate_limiter
        assert isinstance(limiter_a, RedisRateLimiter)
        assert isinstance(limiter_b, RedisRateLimiter)
        assert limiter_a.redis.connection_pool.connection_kwargs["db"] == 1
        assert limiter_b.redis.connection_pool.connection_kwargs["db"] == 2

        assert (
            app_a.state.container.authentication.access_authentication_service.authenticate(
                token_a
            )
            == context
        )
        with pytest.raises(NexusError):
            app_b.state.container.authentication.access_authentication_service.authenticate(
                token_a
            )


def test_application_state_exposes_only_the_root_container() -> None:
    app = create_test_app(build_settings())

    with TestClient(app):
        assert app.state.container.settings.app_name == "NEXUS"
        for legacy_name in (
            "settings",
            "database",
            "authentication",
            "event_publisher",
            "llm",
            "conversations",
        ):
            assert not hasattr(app.state, legacy_name)


def test_lifespan_closes_application_owned_resources() -> None:
    database = TrackingDatabase()
    rate_limiter = TrackingRateLimiter()
    app = create_app(
        build_settings(),
        database=database,  # type: ignore[arg-type]
        rate_limiter=rate_limiter,
        email_provider=StubEmailProvider(),
    )

    with TestClient(app):
        assert database.disposed is False
        assert rate_limiter.closed is False

    assert database.disposed is True
    assert rate_limiter.closed is True


def test_composition_failure_disposes_created_resources() -> None:
    database = TrackingDatabase()

    with pytest.raises(EmailDeliveryError, match="Unsupported email provider"):
        create_app(
            build_settings(email_provider="unsupported"),
            database=database,  # type: ignore[arg-type]
        )

    assert database.disposed is True
