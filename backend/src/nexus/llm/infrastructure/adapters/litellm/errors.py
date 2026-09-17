"""LiteLLM exception translation into NEXUS-owned LLM errors."""

from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType

from nexus.llm.domain import (
    LLMAuthenticationError,
    LLMContentRejectedError,
    LLMError,
    LLMInvalidRequestError,
    LLMProviderUnavailableError,
    LLMRateLimitedError,
    LLMTimeoutError,
    LLMUnknownProviderError,
)

_SAFE_MESSAGE = "LLM provider request failed"


@dataclass(frozen=True)
class LiteLLMExceptionTypes:
    authentication: tuple[type[Exception], ...] = ()
    invalid_request: tuple[type[Exception], ...] = ()
    rate_limited: tuple[type[Exception], ...] = ()
    provider_unavailable: tuple[type[Exception], ...] = ()
    timeout: tuple[type[Exception], ...] = ()
    content_rejected: tuple[type[Exception], ...] = ()

    @property
    def provider_failures(self) -> tuple[type[Exception], ...]:
        return (
            self.authentication
            + self.invalid_request
            + self.rate_limited
            + self.provider_unavailable
            + self.timeout
            + self.content_rejected
        )

    @classmethod
    def from_module(cls, module: ModuleType) -> LiteLLMExceptionTypes:
        return cls(
            authentication=_types(module, "AuthenticationError"),
            invalid_request=_types(module, "BadRequestError", "InvalidRequestError"),
            rate_limited=_types(module, "RateLimitError"),
            provider_unavailable=_types(
                module,
                "APIConnectionError",
                "APIError",
                "ServiceUnavailableError",
            ),
            timeout=_types(module, "Timeout", "TimeoutError", "APITimeoutError"),
            content_rejected=_types(
                module,
                "ContentPolicyViolationError",
                "ContentFilterError",
            ),
        )


def translate_litellm_error(
    exc: Exception,
    exception_types: LiteLLMExceptionTypes,
) -> LLMError:
    if isinstance(exc, exception_types.authentication):
        return LLMAuthenticationError(_SAFE_MESSAGE, safe_details=_safe_details(exc))
    if isinstance(exc, exception_types.content_rejected):
        return LLMContentRejectedError(_SAFE_MESSAGE, safe_details=_safe_details(exc))
    if isinstance(exc, exception_types.invalid_request):
        return LLMInvalidRequestError(_SAFE_MESSAGE, safe_details=_safe_details(exc))
    if isinstance(exc, exception_types.rate_limited):
        return LLMRateLimitedError(_SAFE_MESSAGE, safe_details=_safe_details(exc))
    if isinstance(exc, exception_types.timeout):
        return LLMTimeoutError(_SAFE_MESSAGE, safe_details=_safe_details(exc))
    if isinstance(exc, exception_types.provider_unavailable):
        return LLMProviderUnavailableError(
            _SAFE_MESSAGE,
            safe_details=_safe_details(exc),
        )
    return LLMUnknownProviderError(_SAFE_MESSAGE, safe_details=_safe_details(exc))


def _types(module: ModuleType, *names: str) -> tuple[type[Exception], ...]:
    found: list[type[Exception]] = []
    for name in names:
        value = getattr(module, name, None)
        if isinstance(value, type) and issubclass(value, Exception):
            found.append(value)
    return tuple(found)


def _safe_details(exc: Exception) -> dict[str, str]:
    return {"exception_type": exc.__class__.__name__}
