from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest

from nexus.authentication.gateways import AuthenticationEmailGateway, RateLimiter
from nexus.authentication.repository import (
    AuthenticationIdentity,
    AuthenticationRepository,
    OtpChallenge,
    SignupAccount,
)
from nexus.authentication.session_service import SessionService, SessionTokenResult
from nexus.authentication.signup_service import (
    SignupPolicy,
    SignupService,
    SignupVerificationRequest,
    digest_otp,
)
from nexus.ports.transaction import TransactionManager

NOW = datetime(2026, 9, 21, tzinfo=UTC)
EMAIL = "person@example.com"
OTP = "123456"
OTP_SECRET = "test-otp-secret-with-enough-length"


def build_service(
    *,
    fail_session: bool = False,
) -> tuple[SignupService, Mock, list[str]]:
    events: list[str] = []
    transaction = Mock(spec=TransactionManager)
    repository = Mock(spec=AuthenticationRepository)
    session_service = Mock(spec=SessionService)
    email_gateway = Mock(spec=AuthenticationEmailGateway)

    repository.get_latest_otp_challenge_for_update.return_value = OtpChallenge(
        public_id=uuid4(),
        email=EMAIL,
        purpose="signup",
        code_digest=digest_otp(
            secret=OTP_SECRET,
            email=EMAIL,
            purpose="signup",
            otp=OTP,
        ),
        expires_at=NOW + timedelta(minutes=10),
        max_attempts=5,
    )
    repository.user_exists_by_email.return_value = False
    repository.organization_exists_by_slug.return_value = False

    def create_account(account: SignupAccount) -> AuthenticationIdentity:
        events.append("account")
        return AuthenticationIdentity(
            user_public_id=account.user_public_id,
            organization_public_id=account.organization_public_id,
        )

    def consume_otp(challenge: OtpChallenge) -> None:
        assert challenge.consumed_at == NOW
        events.append("otp")

    def send_welcome_email(*, email: str, display_name: str) -> None:
        del email, display_name
        events.append("welcome-email")

    def stage_session(*, identity: AuthenticationIdentity) -> SessionTokenResult:
        del identity
        events.append("session")
        if fail_session:
            raise RuntimeError("session staging failed")
        return SessionTokenResult(
            access_token="access-token",
            refresh_token="refresh-token",
            token_type="bearer",
            expires_in=900,
        )

    repository.create_organization_administrator.side_effect = create_account
    repository.update_otp_challenge.side_effect = consume_otp
    transaction.commit.side_effect = lambda: events.append("commit")
    transaction.rollback.side_effect = lambda: events.append("rollback")
    email_gateway.send_welcome_email.side_effect = send_welcome_email
    session_service.stage_session.side_effect = stage_session

    return (
        SignupService(
            policy=SignupPolicy(
                otp_hmac_secret=OTP_SECRET,
                signup_otp_length=6,
                signup_otp_ttl_seconds=600,
                signup_otp_max_attempts=5,
                signup_otp_rate_limit_max_requests=5,
                signup_otp_rate_limit_window_seconds=900,
            ),
            transaction=transaction,
            repository=repository,
            session_service=session_service,
            email_gateway=email_gateway,
            rate_limiter=Mock(spec=RateLimiter),
            clock=lambda: NOW,
        ),
        transaction,
        events,
    )


def signup_request() -> SignupVerificationRequest:
    return SignupVerificationRequest(
        email=EMAIL,
        otp=OTP,
        organization_name="Acme",
        first_name="Test",
        last_name="User",
    )


def test_complete_signup_commits_once_after_all_writes_are_staged() -> None:
    service, transaction, events = build_service()

    result = asyncio.run(service.complete_signup(request=signup_request()))

    assert result.status == "completed"
    transaction.commit.assert_awaited_once_with()
    transaction.rollback.assert_not_awaited()
    assert events == ["account", "otp", "session", "commit", "welcome-email"]


def test_session_staging_failure_rolls_back_signup() -> None:
    service, transaction, events = build_service(fail_session=True)

    with pytest.raises(RuntimeError, match="session staging failed"):
        asyncio.run(service.complete_signup(request=signup_request()))

    transaction.commit.assert_not_awaited()
    transaction.rollback.assert_awaited_once_with()
    assert events == ["account", "otp", "session", "rollback"]
