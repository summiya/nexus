from __future__ import annotations

from types import ModuleType

import pytest

from nexus.llm.domain import (
    LLMAuthenticationError,
    LLMInvalidRequestError,
    LLMProviderUnavailableError,
    LLMRateLimitedError,
    LLMTimeoutError,
    LLMUnknownProviderError,
)
from nexus.llm.infrastructure.adapters.litellm.errors import (
    LiteLLMExceptionTypes,
    translate_litellm_error,
)


class AuthenticationError(Exception):
    pass


class BadRequestError(Exception):
    pass


class RateLimitError(Exception):
    pass


class Timeout(Exception):
    pass


class APIConnectionError(Exception):
    pass


def exception_types():
    module = ModuleType("fake_litellm")
    module.AuthenticationError = AuthenticationError
    module.BadRequestError = BadRequestError
    module.RateLimitError = RateLimitError
    module.Timeout = Timeout
    module.APIConnectionError = APIConnectionError
    return LiteLLMExceptionTypes.from_module(module)


@pytest.mark.parametrize(
    ("exc", "expected_type"),
    [
        (AuthenticationError("secret-key leaked?"), LLMAuthenticationError),
        (BadRequestError("prompt body"), LLMInvalidRequestError),
        (RateLimitError("too many"), LLMRateLimitedError),
        (Timeout("timed out"), LLMTimeoutError),
        (APIConnectionError("down"), LLMProviderUnavailableError),
        (RuntimeError("raw provider payload"), LLMUnknownProviderError),
    ],
)
def test_translates_litellm_errors_safely(
    exc: Exception,
    expected_type: type[Exception],
) -> None:
    translated = translate_litellm_error(exc, exception_types())

    assert isinstance(translated, expected_type)
    assert translated.message == "LLM provider request failed"
    assert translated.safe_details == {"exception_type": exc.__class__.__name__}
    assert str(exc) not in translated.message
