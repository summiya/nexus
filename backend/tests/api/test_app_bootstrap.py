from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from nexus.api.dependencies import get_event_publisher
from nexus.config.settings import Settings
from nexus.events import EventEnvelope, EventPublisher, InProcessEventPublisher
from nexus.main import create_app


def build_settings(**overrides: object) -> Settings:
    values = {
        "database_url": "postgresql://test:test@localhost:5432/test",
        "redis_url": "redis://localhost:6379/15",
        "cors_allowed_origins": ["https://nexus.example"],
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
