from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from nexus.errors.codes import (
    ERROR_DEFAULT_MESSAGES,
    HTTP_STATUS_ERROR_CODES,
    ErrorCode,
)
from nexus.errors.exceptions import NexusError
from nexus.errors.models import ErrorBody, ErrorResponse


def _request_id(request: Request) -> str | None:
    """Read an existing request ID without creating request-context infrastructure."""
    request_id = getattr(request.state, "request_id", None)
    return request_id if isinstance(request_id, str) else None


def _response(
    *,
    status_code: int,
    code: ErrorCode,
    message: str,
    request: Request,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            request_id=_request_id(request),
        )
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


async def nexus_error_handler(request: Request, exc: NexusError) -> JSONResponse:
    return _response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        request=request,
    )


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    code = HTTP_STATUS_ERROR_CODES.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
    status_code = exc.status_code if exc.status_code in HTTP_STATUS_ERROR_CODES else 500
    return _response(
        status_code=status_code,
        code=code,
        message=ERROR_DEFAULT_MESSAGES[code],
        request=request,
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return _response(
        status_code=422,
        code=ErrorCode.VALIDATION_ERROR,
        message=ERROR_DEFAULT_MESSAGES[ErrorCode.VALIDATION_ERROR],
        request=request,
    )


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return _response(
        status_code=500,
        code=ErrorCode.INTERNAL_ERROR,
        message=ERROR_DEFAULT_MESSAGES[ErrorCode.INTERNAL_ERROR],
        request=request,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(NexusError, nexus_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unexpected_error_handler)
