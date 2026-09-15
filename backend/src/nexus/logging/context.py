from contextvars import ContextVar, Token
from dataclasses import dataclass

import structlog


@dataclass(frozen=True, slots=True)
class RequestContext:
    request_id: str


_current_request_context: ContextVar[RequestContext | None] = ContextVar(
    "nexus_request_context",
    default=None,
)


def bind_request_context(request_id: str) -> Token[RequestContext | None]:
    """Bind request-scoped metadata for the current async execution context."""
    context = RequestContext(request_id=request_id)
    token = _current_request_context.set(context)
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    return token


def get_request_context() -> RequestContext | None:
    return _current_request_context.get()


def clear_request_context(token: Token[RequestContext | None]) -> None:
    """Restore the previous request context and clear structured log bindings."""
    _current_request_context.reset(token)
    structlog.contextvars.clear_contextvars()
