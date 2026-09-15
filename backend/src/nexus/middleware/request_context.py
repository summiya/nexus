import re
import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from nexus.logging.context import bind_request_context, clear_request_context
from nexus.logging.events import LogEvent
from nexus.logging.logger import get_logger

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
LoggerFactory = Callable[[str | None], Any]


def _new_request_id() -> str:
    return f"req_{uuid4().hex}"


def _resolve_request_id(headers: Headers) -> str:
    incoming = headers.get(REQUEST_ID_HEADER)
    if incoming and _REQUEST_ID_PATTERN.fullmatch(incoming):
        return incoming
    return _new_request_id()


class RequestContextMiddleware:
    """Establish request context and capture the HTTP lifecycle."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        logger_factory: LoggerFactory = get_logger,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.app = app
        self._logger = logger_factory("nexus.request")
        self._clock = clock

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _resolve_request_id(Headers(scope=scope))
        token = bind_request_context(request_id)
        scope.setdefault("state", {})["request_id"] = request_id
        method = scope.get("method", "")
        route = scope.get("path", "")
        started_at = self._clock()
        status_code = 500

        self._logger.info(
            LogEvent.REQUEST_STARTED,
            request_id=request_id,
            method=method,
            route=route,
        )

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            self._logger.error(
                LogEvent.REQUEST_FAILED,
                request_id=request_id,
                method=method,
                route=route,
                status_code=500,
                duration_ms=round((self._clock() - started_at) * 1000, 3),
            )
            raise
        else:
            self._logger.info(
                LogEvent.REQUEST_COMPLETED,
                request_id=request_id,
                method=method,
                route=route,
                status_code=status_code,
                duration_ms=round((self._clock() - started_at) * 1000, 3),
            )
        finally:
            clear_request_context(token)
