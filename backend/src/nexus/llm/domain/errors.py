"""NEXUS-owned LLM error contracts."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class LLMErrorKind(StrEnum):
    AUTHENTICATION = "authentication"
    INVALID_REQUEST = "invalid_request"
    RATE_LIMITED = "rate_limited"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    TIMEOUT = "timeout"
    CONTENT_REJECTED = "content_rejected"
    UNKNOWN_PROVIDER_FAILURE = "unknown_provider_failure"


class LLMError(Exception):
    """Base provider-independent LLM error."""

    kind: LLMErrorKind = LLMErrorKind.UNKNOWN_PROVIDER_FAILURE
    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        safe_details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.safe_details = MappingProxyType(dict(safe_details or {}))


class LLMAuthenticationError(LLMError):
    kind = LLMErrorKind.AUTHENTICATION


class LLMInvalidRequestError(LLMError):
    kind = LLMErrorKind.INVALID_REQUEST


class LLMRateLimitedError(LLMError):
    kind = LLMErrorKind.RATE_LIMITED
    retryable = True


class LLMProviderUnavailableError(LLMError):
    kind = LLMErrorKind.PROVIDER_UNAVAILABLE
    retryable = True


class LLMTimeoutError(LLMError):
    kind = LLMErrorKind.TIMEOUT
    retryable = True


class LLMContentRejectedError(LLMError):
    kind = LLMErrorKind.CONTENT_REJECTED


class LLMUnknownProviderError(LLMError):
    kind = LLMErrorKind.UNKNOWN_PROVIDER_FAILURE
