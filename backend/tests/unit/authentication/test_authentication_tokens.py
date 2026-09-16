from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from nexus.security.authentication_tokens import (
    AccessTokenError,
    AccessTokenExpiredError,
    AccessTokenService,
    AuthTokenContext,
)


def test_access_token_round_trip() -> None:
    context = AuthTokenContext(
        user_public_id=uuid4(),
        organization_public_id=uuid4(),
        session_public_id=uuid4(),
    )
    service = AccessTokenService(
        secret="test-auth-token-secret-with-enough-length",
        expires_seconds=900,
        issuer="nexus-test",
        clock=lambda: datetime.now(UTC),
    )

    token = service.issue_access_token(context)

    assert service.verify_access_token(token) == context


def test_access_token_contains_expected_claims() -> None:
    context = AuthTokenContext(
        user_public_id=uuid4(),
        organization_public_id=uuid4(),
        session_public_id=uuid4(),
    )
    service = AccessTokenService(
        secret="test-auth-token-secret-with-enough-length",
        expires_seconds=900,
        issuer="nexus-test",
        clock=lambda: datetime.now(UTC),
    )

    token = service.issue_access_token(context)
    claims = jwt.decode(
        token,
        "test-auth-token-secret-with-enough-length",
        algorithms=["HS256"],
        issuer="nexus-test",
    )

    assert claims["sub"] == str(context.user_public_id)
    assert claims["org"] == str(context.organization_public_id)
    assert claims["sid"] == str(context.session_public_id)
    assert claims["typ"] == "access"


def test_expired_access_token_is_rejected() -> None:
    context = AuthTokenContext(
        user_public_id=uuid4(),
        organization_public_id=uuid4(),
        session_public_id=uuid4(),
    )
    service = AccessTokenService(
        secret="test-auth-token-secret-with-enough-length",
        expires_seconds=1,
        clock=lambda: datetime.now(UTC) - timedelta(seconds=10),
    )

    token = service.issue_access_token(context)

    with pytest.raises(AccessTokenExpiredError):
        service.verify_access_token(token)


def test_invalid_signature_is_rejected() -> None:
    context = AuthTokenContext(
        user_public_id=uuid4(),
        organization_public_id=uuid4(),
        session_public_id=uuid4(),
    )
    issuer = AccessTokenService(
        secret="test-auth-token-secret-with-enough-length",
        expires_seconds=900,
    )
    verifier = AccessTokenService(
        secret="different-auth-token-secret-with-enough-length",
        expires_seconds=900,
    )

    with pytest.raises(AccessTokenError):
        verifier.verify_access_token(issuer.issue_access_token(context))


def test_token_values_are_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    service = AccessTokenService(
        secret="test-auth-token-secret-with-enough-length",
        expires_seconds=900,
    )
    token = service.issue_access_token(
        AuthTokenContext(
            user_public_id=uuid4(),
            organization_public_id=uuid4(),
            session_public_id=uuid4(),
        )
    )

    assert token not in caplog.text
    assert "test-auth-token-secret-with-enough-length" not in caplog.text
