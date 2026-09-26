from collections.abc import AsyncIterator
from typing import Annotated
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from nexus.api.dependencies import get_event_publisher
from nexus.authentication.tokens import AuthTokenContext
from nexus.composition import root as composition_root
from nexus.config.settings import Settings
from nexus.errors import NexusError
from nexus.events import EventEnvelope, EventPublisher, InProcessEventPublisher
from nexus.files.ports import DownloadGrantIssuer, ObjectStorage, UploadGrantIssuer
from nexus.infrastructure.mailer import EmailDeliveryError, EmailMessage
from nexus.infrastructure.persistence.conversation import (
    SqlAlchemyConversationPersistence,
)
from nexus.infrastructure.rate_limit import RedisRateLimiter
from nexus.infrastructure.upload_context import AesGcmUploadContextProtector
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
    async def allow(self, *, key: str, limit: int, window_seconds: int) -> bool:
        del key, limit, window_seconds
        return True


class TrackingRateLimiter(AllowAllRateLimiter):
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FailingTrackingRateLimiter(TrackingRateLimiter):
    def close(self) -> None:
        super().close()
        raise RuntimeError("rate limiter cleanup failed")


class StubEmailProvider:
    def send(self, message: EmailMessage) -> None:
        del message


class TrackingDatabase:
    def __init__(self) -> None:
        self.dispose_calls = 0
        self.session_factory = lambda: None

    async def dispose(self) -> None:
        self.dispose_calls += 1


class TrackingStorageComposition:
    def __init__(self) -> None:
        self.object_storage = Mock(spec=ObjectStorage)
        self.upload_grant_issuer = Mock(spec=UploadGrantIssuer)
        self.download_grant_issuer = Mock(spec=DownloadGrantIssuer)
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


class FailingTrackingStorageComposition(TrackingStorageComposition):
    async def close(self) -> None:
        await super().close()
        raise RuntimeError("storage cleanup failed")


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
        "file_upload_context_key": ("bmV4dXMtZGV2ZWxvcG1lbnQtdXBsb2FkLWtleS0wMDE"),
        **overrides,
    }
    if "debug" in values:
        values["APP_DEBUG"] = values.pop("debug")
    return Settings(_env_file=None, **values)


def create_test_app(settings: Settings, **overrides: object) -> FastAPI:
    overrides.setdefault("object_storage", Mock(spec=ObjectStorage))
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


def test_llm_gateway_and_model_policy_are_application_scoped() -> None:
    gateway = FakeLLMGateway()
    app = create_test_app(build_settings(), llm_gateway=gateway)

    with TestClient(app):
        assert app.state.container.llm.gateway is gateway
        assert app.state.container.conversations.stream_message.llm_gateway is gateway


def test_conversation_composition_receives_database_session_factory() -> None:
    database = TrackingDatabase()
    app = create_test_app(build_settings(), database=database)

    with TestClient(app):
        persistence = app.state.container.conversations.create.persistence
        assert isinstance(persistence, SqlAlchemyConversationPersistence)
        assert persistence._session_factory is database.session_factory


def test_file_composition_receives_shared_runtime_dependencies() -> None:
    database = TrackingDatabase()
    issuer = Mock(spec=UploadGrantIssuer)
    app = create_test_app(
        build_settings(
            file_upload_max_size_bytes=123_456,
            file_upload_grant_ttl_seconds=900,
        ),
        database=database,
        upload_grant_issuer=issuer,
    )

    with TestClient(app):
        service = app.state.container.files.initiate_upload
        assert service.intent_policy.max_size_bytes == 123_456
        assert service.permission_checker._session_factory is database.session_factory
        assert service.upload_grant_issuer is issuer
        assert isinstance(service.context_protector, AesGcmUploadContextProtector)
        assert service.grant_ttl.total_seconds() == 900


def test_unsupported_llm_gateway_fails_during_application_composition() -> None:
    app = create_test_app(build_settings(llm_gateway="unsupported"))

    with (
        pytest.raises(
            UnsupportedLLMGatewayError,
            match="Unsupported LLM gateway configuration",
        ),
        TestClient(app),
    ):
        pass


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
    app_a = create_app(
        settings_a,
        email_provider=StubEmailProvider(),
        object_storage=Mock(spec=ObjectStorage),
    )
    app_b = create_app(
        settings_b,
        email_provider=StubEmailProvider(),
        object_storage=Mock(spec=ObjectStorage),
    )

    context = AuthTokenContext(
        user_public_id=uuid4(),
        organization_public_id=uuid4(),
        session_public_id=uuid4(),
    )
    with TestClient(app_a), TestClient(app_b):
        token_a = app_a.state.container.authentication.access_token_service.issue_access_token(
            context
        )
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
            "llm_gateway",
            "rate_limiter",
            "email_provider",
            "object_storage",
            "upload_grant_issuer",
            "bootstrap_dependencies",
            "llm",
            "conversations",
            "storage",
            "files",
        ):
            assert not hasattr(app.state, legacy_name)


def test_lifespan_forwards_storage_override_to_async_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = TrackingDatabase()
    injected_storage = Mock(spec=ObjectStorage)
    injected_issuer = Mock(spec=UploadGrantIssuer)
    injected_download_issuer = Mock(spec=DownloadGrantIssuer)
    tracking_composition = TrackingStorageComposition()
    captured: dict[str, object] = {}

    async def build_tracking_storage(
        settings: Settings,
        *,
        object_storage: ObjectStorage | None = None,
        upload_grant_issuer: UploadGrantIssuer | None = None,
        download_grant_issuer: DownloadGrantIssuer | None = None,
    ) -> TrackingStorageComposition:
        captured["settings"] = settings
        captured["object_storage"] = object_storage
        captured["upload_grant_issuer"] = upload_grant_issuer
        captured["download_grant_issuer"] = download_grant_issuer
        tracking_composition.object_storage = object_storage
        tracking_composition.upload_grant_issuer = upload_grant_issuer
        tracking_composition.download_grant_issuer = download_grant_issuer
        return tracking_composition

    monkeypatch.setattr(
        composition_root,
        "build_storage_composition",
        build_tracking_storage,
    )
    settings = build_settings()
    app = create_app(
        settings,
        database=database,  # type: ignore[arg-type]
        rate_limiter=AllowAllRateLimiter(),
        email_provider=StubEmailProvider(),
        object_storage=injected_storage,
        upload_grant_issuer=injected_issuer,
        download_grant_issuer=injected_download_issuer,
    )

    assert not hasattr(app.state, "container")
    with TestClient(app):
        assert captured == {
            "settings": settings,
            "object_storage": injected_storage,
            "upload_grant_issuer": injected_issuer,
            "download_grant_issuer": injected_download_issuer,
        }
        assert app.state.container.storage.object_storage is injected_storage
        assert app.state.container.storage.upload_grant_issuer is injected_issuer
        assert (
            app.state.container.storage.download_grant_issuer
            is injected_download_issuer
        )

    assert tracking_composition.close_calls == 1
    assert database.dispose_calls == 1


def test_lifespan_closes_application_owned_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = TrackingDatabase()
    rate_limiter = TrackingRateLimiter()
    storage = TrackingStorageComposition()

    async def build_tracking_storage(
        settings: Settings,
        *,
        object_storage: ObjectStorage | None = None,
        upload_grant_issuer: UploadGrantIssuer | None = None,
        download_grant_issuer: DownloadGrantIssuer | None = None,
    ) -> TrackingStorageComposition:
        del settings, object_storage, upload_grant_issuer, download_grant_issuer
        return storage

    monkeypatch.setattr(
        composition_root,
        "build_storage_composition",
        build_tracking_storage,
    )
    app = create_app(
        build_settings(),
        database=database,  # type: ignore[arg-type]
        rate_limiter=rate_limiter,
        email_provider=StubEmailProvider(),
    )

    with TestClient(app):
        assert database.dispose_calls == 0
        assert rate_limiter.closed is False

    assert database.dispose_calls == 1
    assert rate_limiter.closed is True
    assert storage.close_calls == 1


def test_lifespan_closes_storage_and_database_when_authentication_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = TrackingDatabase()
    rate_limiter = FailingTrackingRateLimiter()
    storage = TrackingStorageComposition()

    async def build_tracking_storage(
        settings: Settings,
        *,
        object_storage: ObjectStorage | None = None,
        upload_grant_issuer: UploadGrantIssuer | None = None,
        download_grant_issuer: DownloadGrantIssuer | None = None,
    ) -> TrackingStorageComposition:
        del settings, object_storage, upload_grant_issuer, download_grant_issuer
        return storage

    monkeypatch.setattr(
        composition_root,
        "build_storage_composition",
        build_tracking_storage,
    )
    app = create_app(
        build_settings(),
        database=database,  # type: ignore[arg-type]
        rate_limiter=rate_limiter,
        email_provider=StubEmailProvider(),
    )

    with (
        pytest.raises(RuntimeError, match="rate limiter cleanup failed"),
        TestClient(app),
    ):
        pass

    assert rate_limiter.closed is True
    assert storage.close_calls == 1
    assert database.dispose_calls == 1


def test_lifespan_disposes_database_when_storage_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = TrackingDatabase()
    storage = FailingTrackingStorageComposition()

    async def build_tracking_storage(
        settings: Settings,
        *,
        object_storage: ObjectStorage | None = None,
        upload_grant_issuer: UploadGrantIssuer | None = None,
        download_grant_issuer: DownloadGrantIssuer | None = None,
    ) -> FailingTrackingStorageComposition:
        del settings, object_storage, upload_grant_issuer, download_grant_issuer
        return storage

    monkeypatch.setattr(
        composition_root,
        "build_storage_composition",
        build_tracking_storage,
    )
    app = create_app(
        build_settings(),
        database=database,  # type: ignore[arg-type]
        rate_limiter=AllowAllRateLimiter(),
        email_provider=StubEmailProvider(),
    )

    with (
        pytest.raises(RuntimeError, match="storage cleanup failed"),
        TestClient(app),
    ):
        pass

    assert storage.close_calls == 1
    assert database.dispose_calls == 1


def test_storage_composition_failure_cleans_earlier_owned_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = TrackingDatabase()
    rate_limiter = TrackingRateLimiter()

    async def fail_storage_composition(
        settings: Settings,
        *,
        object_storage: ObjectStorage | None = None,
        upload_grant_issuer: UploadGrantIssuer | None = None,
        download_grant_issuer: DownloadGrantIssuer | None = None,
    ) -> TrackingStorageComposition:
        del settings, object_storage, upload_grant_issuer, download_grant_issuer
        raise RuntimeError("storage composition failed")

    monkeypatch.setattr(
        composition_root,
        "build_storage_composition",
        fail_storage_composition,
    )
    app = create_app(
        build_settings(),
        database=database,  # type: ignore[arg-type]
        rate_limiter=rate_limiter,
        email_provider=StubEmailProvider(),
    )

    with (
        pytest.raises(RuntimeError, match="storage composition failed"),
        TestClient(app),
    ):
        pass

    assert rate_limiter.closed is True
    assert database.dispose_calls == 1
    assert not hasattr(app.state, "container")


def test_file_composition_failure_closes_all_earlier_owned_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = TrackingDatabase()
    rate_limiter = TrackingRateLimiter()
    storage = TrackingStorageComposition()

    async def build_tracking_storage(
        settings: Settings,
        *,
        object_storage: ObjectStorage | None = None,
        upload_grant_issuer: UploadGrantIssuer | None = None,
        download_grant_issuer: DownloadGrantIssuer | None = None,
    ) -> TrackingStorageComposition:
        del settings, object_storage, upload_grant_issuer, download_grant_issuer
        return storage

    def fail_file_composition(
        settings: Settings,
        *,
        session_factory: object,
        upload_grant_issuer: UploadGrantIssuer,
        download_grant_issuer: DownloadGrantIssuer,
    ) -> None:
        del settings, session_factory, upload_grant_issuer, download_grant_issuer
        raise RuntimeError("file composition failed")

    monkeypatch.setattr(
        composition_root,
        "build_storage_composition",
        build_tracking_storage,
    )
    monkeypatch.setattr(
        composition_root,
        "build_file_composition",
        fail_file_composition,
    )
    app = create_app(
        build_settings(),
        database=database,  # type: ignore[arg-type]
        rate_limiter=rate_limiter,
        email_provider=StubEmailProvider(),
    )

    with (
        pytest.raises(RuntimeError, match="file composition failed"),
        TestClient(app),
    ):
        pass

    assert rate_limiter.closed is True
    assert storage.close_calls == 1
    assert database.dispose_calls == 1
    assert not hasattr(app.state, "container")


def test_authentication_composition_failure_does_not_adopt_database() -> None:
    database = TrackingDatabase()
    app = create_app(
        build_settings(email_provider="unsupported"),
        database=database,  # type: ignore[arg-type]
        object_storage=Mock(spec=ObjectStorage),
    )

    with (
        pytest.raises(EmailDeliveryError, match="Unsupported email provider"),
        TestClient(app),
    ):
        pass

    assert database.dispose_calls == 0


def test_database_construction_failure_closes_authentication_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rate_limiter = TrackingRateLimiter()

    def fail_database_construction(database_url: str) -> None:
        del database_url
        raise RuntimeError("database construction failed")

    monkeypatch.setattr(
        composition_root,
        "build_database",
        fail_database_construction,
    )

    app = create_app(
        build_settings(),
        rate_limiter=rate_limiter,
        email_provider=StubEmailProvider(),
        object_storage=Mock(spec=ObjectStorage),
    )

    with (
        pytest.raises(RuntimeError, match="database construction failed"),
        TestClient(app),
    ):
        pass

    assert rate_limiter.closed is True
