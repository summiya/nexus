from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest

from nexus.authentication.gateways import AuthenticationEmailGateway, RateLimiter
from nexus.authentication.login_service import (
    LoginPolicy,
    LoginService,
    LoginVerificationRequest,
)
from nexus.authentication.otp import digest_otp
from nexus.authentication.repository import (
    AuthenticationIdentity,
    AuthenticationRepository,
    OtpChallenge,
)
from nexus.authentication.session_service import SessionService, SessionTokenResult
from nexus.errors import ErrorCode, NexusError
from nexus.ports.transaction import TransactionManager

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
EMAIL = "user@example.com"
OTP = "123456"
OTP_SECRET = "test-secret-value-with-enough-length"


def login_challenge(
    *,
    purpose: str = "login",
    expires_at: datetime | None = None,
    attempt_count: int = 0,
    consumed_at: datetime | None = None,
    locked_at: datetime | None = None,
) -> OtpChallenge:
    return OtpChallenge(
        public_id=uuid4(),
        email=EMAIL,
        purpose=purpose,
        code_digest=digest_otp(
            secret=OTP_SECRET,
            email=EMAIL,
            purpose=purpose,
            otp=OTP,
        ),
        expires_at=expires_at or NOW + timedelta(minutes=5),
        max_attempts=5,
        attempt_count=attempt_count,
        consumed_at=consumed_at,
        locked_at=locked_at,
    )


def identity() -> AuthenticationIdentity:
    return AuthenticationIdentity(
        user_public_id=uuid4(),
        organization_public_id=uuid4(),
    )


def token_result() -> SessionTokenResult:
    return SessionTokenResult(
        access_token="access-token",
        refresh_token="refresh-token",
        token_type="bearer",
        expires_in=900,
    )


def build_service() -> tuple[LoginService, Mock, Mock, Mock]:
    repository = Mock(spec=AuthenticationRepository)
    transaction = Mock(spec=TransactionManager)
    session_service = Mock(spec=SessionService)
    repository.get_latest_otp_challenge_for_update.return_value = login_challenge()
    repository.get_identity_by_email.return_value = identity()
    session_service.stage_session.return_value = token_result()
    return (
        LoginService(
            policy=LoginPolicy(
                otp_hmac_secret=OTP_SECRET,
                otp_length=6,
                otp_ttl_seconds=600,
                otp_max_attempts=5,
                otp_rate_limit_max_requests=5,
                otp_rate_limit_window_seconds=900,
            ),
            transaction=transaction,
            repository=repository,
            session_service=session_service,
            email_gateway=Mock(spec=AuthenticationEmailGateway),
            rate_limiter=Mock(spec=RateLimiter),
            clock=lambda: NOW,
        ),
        repository,
        session_service,
        transaction,
    )


def assert_invalid_credentials(exc: NexusError) -> None:
    assert exc.code == ErrorCode.UNAUTHORIZED
    assert exc.message == "Authentication credentials are invalid."


def test_valid_login_otp_consumes_challenge_stages_session_and_commits_once() -> None:
    service, repository, session_service, transaction = build_service()
    expected_identity = repository.get_identity_by_email.return_value
    events: list[str] = []
    repository.update_otp_challenge.side_effect = lambda _challenge: events.append(
        "otp"
    )
    session_service.stage_session.side_effect = lambda **_kwargs: (
        events.append("session") or token_result()
    )
    transaction.commit.side_effect = lambda: events.append("commit")

    result = service.verify_login_otp(
        request=LoginVerificationRequest(
            email="  USER@Example.COM ",
            otp=OTP,
        )
    )

    assert result == token_result()
    repository.get_latest_otp_challenge_for_update.assert_called_once_with(
        email=EMAIL,
        purpose="login",
    )
    repository.get_identity_by_email.assert_called_once_with(EMAIL)
    consumed = repository.update_otp_challenge.call_args.args[0]
    assert consumed.consumed_at == NOW
    session_service.stage_session.assert_called_once_with(identity=expected_identity)
    transaction.commit.assert_called_once_with()
    transaction.rollback.assert_not_called()
    assert events == ["otp", "session", "commit"]


def test_signup_purpose_challenge_cannot_verify_login() -> None:
    service, repository, session_service, transaction = build_service()
    repository.get_latest_otp_challenge_for_update.return_value = login_challenge(
        purpose="signup"
    )

    with pytest.raises(NexusError) as exc_info:
        service.verify_login_otp(request=LoginVerificationRequest(email=EMAIL, otp=OTP))

    assert_invalid_credentials(exc_info.value)
    session_service.stage_session.assert_not_called()
    transaction.rollback.assert_called_once_with()


@pytest.mark.parametrize(
    "challenge",
    [
        None,
        login_challenge(expires_at=NOW - timedelta(seconds=1)),
        login_challenge(consumed_at=NOW - timedelta(seconds=1)),
        login_challenge(locked_at=NOW - timedelta(seconds=1)),
    ],
    ids=["missing", "expired", "consumed", "locked"],
)
def test_invalid_challenge_state_returns_generic_unauthorized(
    challenge: OtpChallenge | None,
) -> None:
    service, repository, session_service, transaction = build_service()
    repository.get_latest_otp_challenge_for_update.return_value = challenge

    with pytest.raises(NexusError) as exc_info:
        service.verify_login_otp(request=LoginVerificationRequest(email=EMAIL, otp=OTP))

    assert_invalid_credentials(exc_info.value)
    repository.update_otp_challenge.assert_not_called()
    session_service.stage_session.assert_not_called()
    transaction.rollback.assert_called_once_with()


@pytest.mark.parametrize("otp", ["", "12345", "1234567", "12a456"])
def test_malformed_otp_returns_generic_unauthorized_without_lookup(otp: str) -> None:
    service, repository, session_service, transaction = build_service()

    with pytest.raises(NexusError) as exc_info:
        service.verify_login_otp(request=LoginVerificationRequest(email=EMAIL, otp=otp))

    assert_invalid_credentials(exc_info.value)
    repository.get_latest_otp_challenge_for_update.assert_not_called()
    session_service.stage_session.assert_not_called()
    transaction.rollback.assert_called_once_with()


def test_wrong_otp_commits_incremented_attempt_state() -> None:
    service, repository, session_service, transaction = build_service()
    original = login_challenge(attempt_count=2)
    repository.get_latest_otp_challenge_for_update.return_value = original

    with pytest.raises(NexusError) as exc_info:
        service.verify_login_otp(
            request=LoginVerificationRequest(email=EMAIL, otp="654321")
        )

    assert_invalid_credentials(exc_info.value)
    updated = repository.update_otp_challenge.call_args.args[0]
    assert updated.attempt_count == 3
    assert updated.locked_at is None
    session_service.stage_session.assert_not_called()
    transaction.commit.assert_called_once_with()
    transaction.rollback.assert_not_called()


def test_final_wrong_attempt_commits_locked_challenge() -> None:
    service, repository, session_service, transaction = build_service()
    original = login_challenge(attempt_count=4)
    repository.get_latest_otp_challenge_for_update.return_value = original

    with pytest.raises(NexusError) as exc_info:
        service.verify_login_otp(
            request=LoginVerificationRequest(email=EMAIL, otp="654321")
        )

    assert_invalid_credentials(exc_info.value)
    updated = repository.update_otp_challenge.call_args.args[0]
    assert updated.attempt_count == 5
    assert updated.locked_at == NOW
    session_service.stage_session.assert_not_called()
    transaction.commit.assert_called_once_with()


def test_missing_active_identity_returns_generic_unauthorized() -> None:
    service, repository, session_service, transaction = build_service()
    repository.get_identity_by_email.return_value = None

    with pytest.raises(NexusError) as exc_info:
        service.verify_login_otp(request=LoginVerificationRequest(email=EMAIL, otp=OTP))

    assert_invalid_credentials(exc_info.value)
    repository.update_otp_challenge.assert_not_called()
    session_service.stage_session.assert_not_called()
    transaction.rollback.assert_called_once_with()


def test_session_staging_failure_rolls_back_and_preserves_safe_error() -> None:
    service, repository, session_service, transaction = build_service()
    session_service.stage_session.side_effect = NexusError(
        ErrorCode.SERVICE_UNAVAILABLE,
        "The service is temporarily unavailable.",
        retryable=True,
    )

    with pytest.raises(NexusError) as exc_info:
        service.verify_login_otp(request=LoginVerificationRequest(email=EMAIL, otp=OTP))

    assert exc_info.value.code == ErrorCode.SERVICE_UNAVAILABLE
    assert repository.update_otp_challenge.call_args.args[0].consumed_at == NOW
    transaction.commit.assert_not_called()
    transaction.rollback.assert_called_once_with()


def test_unexpected_repository_failure_rolls_back_without_translation() -> None:
    service, repository, session_service, transaction = build_service()
    repository.get_identity_by_email.side_effect = RuntimeError("database failed")

    with pytest.raises(RuntimeError, match="database failed"):
        service.verify_login_otp(request=LoginVerificationRequest(email=EMAIL, otp=OTP))

    session_service.stage_session.assert_not_called()
    transaction.commit.assert_not_called()
    transaction.rollback.assert_called_once_with()
