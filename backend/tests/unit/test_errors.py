import pytest

from nexus.errors.codes import ERROR_STATUS_CODES, ErrorCode
from nexus.errors.exceptions import NexusError

EXPECTED_STATUS_CODES = {
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.BAD_REQUEST: 400,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.SERVICE_UNAVAILABLE: 503,
    ErrorCode.INTERNAL_ERROR: 500,
}


@pytest.mark.parametrize(("code", "status_code"), EXPECTED_STATUS_CODES.items())
def test_canonical_status_mapping(code: ErrorCode, status_code: int) -> None:
    assert ERROR_STATUS_CODES[code] == status_code


def test_nexus_error_defaults() -> None:
    error = NexusError(ErrorCode.NOT_FOUND, "Resource not found")

    assert error.code is ErrorCode.NOT_FOUND
    assert error.message == "Resource not found"
    assert error.status_code == 404
    assert error.details is None
    assert error.retryable is False
    assert str(error) == "Resource not found"


def test_nexus_error_optional_fields() -> None:
    error = NexusError(
        ErrorCode.SERVICE_UNAVAILABLE,
        "Provider unavailable",
        details={"provider": "test"},
        retryable=True,
    )

    assert error.details == {"provider": "test"}
    assert error.retryable is True
    assert error.status_code == 503


def test_status_code_is_derived_from_code() -> None:
    error = NexusError(ErrorCode.CONFLICT, "Conflict")

    assert error.status_code == ERROR_STATUS_CODES[ErrorCode.CONFLICT]
