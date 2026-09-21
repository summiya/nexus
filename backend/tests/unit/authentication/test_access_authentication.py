from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from nexus.authentication.tokens import (
    AccessAuthenticationService,
    AccessTokenService,
    AuthTokenContext,
)
from nexus.errors import ErrorCode, NexusError


def _token_service(*, expired: bool = False) -> AccessTokenService:
    now = datetime.now(UTC)
    if expired:
        now -= timedelta(minutes=10)
    return AccessTokenService(
        secret="test-auth-token-secret-with-enough-length",
        expires_seconds=60,
        issuer="nexus-test",
        clock=lambda: now,
    )


def test_authenticate_returns_trusted_token_context() -> None:
    token_service = _token_service()
    expected = AuthTokenContext(
        user_public_id=uuid4(),
        organization_public_id=uuid4(),
        session_public_id=uuid4(),
    )
    token = token_service.issue_access_token(expected)
    service = AccessAuthenticationService(access_token_service=token_service)

    assert service.authenticate(token) == expected


def test_authenticate_rejects_invalid_token_without_exposing_token() -> None:
    service = AccessAuthenticationService(access_token_service=_token_service())
    token = "not-a-valid-jwt"

    with pytest.raises(NexusError) as exc_info:
        service.authenticate(token)

    assert exc_info.value.code == ErrorCode.ACCESS_TOKEN_INVALID
    assert exc_info.value.status_code == 401
    assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}
    assert token not in str(exc_info.value)


def test_authenticate_rejects_expired_token_with_distinct_error() -> None:
    token_service = _token_service(expired=True)
    token = token_service.issue_access_token(
        AuthTokenContext(
            user_public_id=uuid4(),
            organization_public_id=uuid4(),
            session_public_id=uuid4(),
        )
    )
    service = AccessAuthenticationService(access_token_service=token_service)

    with pytest.raises(NexusError) as exc_info:
        service.authenticate(token)

    assert exc_info.value.code == ErrorCode.ACCESS_TOKEN_EXPIRED
    assert exc_info.value.status_code == 401
    assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}
