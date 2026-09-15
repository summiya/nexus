from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from nexus.errors import ErrorCode, NexusError
from nexus.errors.handlers import register_exception_handlers


def _test_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/nexus-error")
    async def nexus_error() -> None:
        raise NexusError(ErrorCode.NOT_FOUND, "The requested resource was not found.")

    @app.get("/http-error")
    async def http_error() -> None:
        raise HTTPException(status_code=403, detail="internal framework detail")

    @app.get("/validate/{item_id}")
    async def validate(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    @app.get("/unexpected")
    async def unexpected() -> None:
        raise RuntimeError(
            "password=SUPER_SECRET token=TOP_SECRET_TOKEN "
            "/path/to/internal/file.py postgresql://user:secret@database"
        )

    @app.get("/request-id")
    async def request_id() -> None:
        raise NexusError(ErrorCode.CONFLICT, "Conflict")

    return app


def test_nexus_error_is_normalized() -> None:
    with TestClient(_test_app()) as client:
        response = client.get("/nexus-error")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "The requested resource was not found.",
            "request_id": None,
        }
    }


def test_http_exception_is_normalized_without_exposing_detail() -> None:
    with TestClient(_test_app()) as client:
        response = client.get("/http-error")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert "internal framework detail" not in response.text


def test_validation_error_is_normalized() -> None:
    with TestClient(_test_app()) as client:
        response = client.get("/validate/not-an-integer")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_unexpected_error_is_sanitized() -> None:
    with TestClient(_test_app(), raise_server_exceptions=False) as client:
        response = client.get("/unexpected")

    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "An internal server error occurred.",
        "request_id": None,
    }
    for sensitive_value in (
        "SUPER_SECRET",
        "TOP_SECRET_TOKEN",
        "/path/to/internal/file.py",
        "postgresql://user:secret@database",
    ):
        assert sensitive_value not in response.text


def test_existing_request_id_is_propagated_without_generation() -> None:
    app = _test_app()

    @app.middleware("http")
    async def existing_request_id(request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = "req_test_123"
        return await call_next(request)

    with TestClient(app) as client:
        response = client.get("/request-id")

    assert response.status_code == 409
    assert response.json()["error"]["request_id"] == "req_test_123"


def test_custom_nexus_error_subclass_uses_same_handler() -> None:
    class ConversationNotFoundError(NexusError):
        def __init__(self) -> None:
            super().__init__(ErrorCode.NOT_FOUND, "Conversation not found.")

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/conversation")
    async def conversation() -> None:
        raise ConversationNotFoundError()

    with TestClient(app) as client:
        response = client.get("/conversation")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert response.json()["error"]["message"] == "Conversation not found."
