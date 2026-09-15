import json

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from nexus.errors import ErrorCode, NexusError
from nexus.errors.handlers import register_exception_handlers
from nexus.logging.context import get_request_context
from nexus.middleware import RequestContextMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(RequestContextMiddleware)

    @app.get("/ok")
    async def ok(request: Request) -> dict[str, str | None]:
        context = get_request_context()
        return {
            "request_id": context.request_id if context else None,
            "state_request_id": request.state.request_id,
        }

    @app.get("/error")
    async def error() -> None:
        raise NexusError(ErrorCode.CONFLICT, "Conflict")

    @app.post("/safe")
    async def safe() -> dict[str, bool]:
        return {"ok": True}

    return app


def _json_logs(capsys) -> list[dict[str, object]]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]


def test_request_id_is_generated_and_available() -> None:
    with TestClient(_app()) as client:
        response = client.get("/ok")

    request_id = response.headers["X-Request-ID"]
    assert request_id.startswith("req_")
    assert response.json()["request_id"] == request_id
    assert response.json()["state_request_id"] == request_id


def test_valid_incoming_request_id_is_preserved() -> None:
    with TestClient(_app()) as client:
        response = client.get("/ok", headers={"X-Request-ID": "req_client_123"})

    assert response.headers["X-Request-ID"] == "req_client_123"
    assert response.json()["request_id"] == "req_client_123"


def test_invalid_incoming_request_id_is_replaced() -> None:
    with TestClient(_app()) as client:
        response = client.get("/ok", headers={"X-Request-ID": "bad id with spaces"})

    assert response.headers["X-Request-ID"].startswith("req_")
    assert response.headers["X-Request-ID"] != "bad id with spaces"


def test_error_response_uses_same_request_id() -> None:
    with TestClient(_app()) as client:
        response = client.get("/error", headers={"X-Request-ID": "req_error_123"})

    assert response.status_code == 409
    assert response.headers["X-Request-ID"] == "req_error_123"
    assert response.json()["error"]["request_id"] == "req_error_123"


def test_lifecycle_logs_have_required_fields(capsys) -> None:
    with TestClient(_app()) as client:
        response = client.get("/ok", headers={"X-Request-ID": "req_log_123"})

    logs = _json_logs(capsys)
    completed = next(log for log in logs if log["event"] == "request_completed")
    assert completed["request_id"] == "req_log_123"
    assert completed["method"] == "GET"
    assert completed["route"] == "/ok"
    assert completed["status_code"] == response.status_code
    assert isinstance(completed["duration_ms"], (int, float))
    assert completed["duration_ms"] >= 0
    assert completed["level"] == "info"
    assert "timestamp" in completed


def test_sensitive_request_data_is_not_logged(capsys) -> None:
    secret = "TOP_SECRET_VALUE"
    with TestClient(_app()) as client:
        response = client.post(
            "/safe?token=query-secret",
            headers={"Authorization": f"Bearer {secret}"},
            json={"password": secret, "prompt": secret},
        )

    assert response.status_code == 200
    output = capsys.readouterr().out
    assert secret not in output
    assert "query-secret" not in output
    assert "Authorization" not in output
    assert "password" not in output
