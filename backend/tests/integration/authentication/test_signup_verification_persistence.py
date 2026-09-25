from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from nexus.authentication.gateways import (
    AccessTokenClaims,
    AccessTokenGateway,
    AccessTokenGatewayError,
    AuthenticationEmailError,
)
from nexus.authentication.session_service import SessionPolicy, SessionService
from nexus.authentication.signup_service import (
    SignupPolicy,
    SignupService,
    SignupVerificationRequest,
    SignupVerificationResult,
    digest_otp,
)
from nexus.authentication.tokens import AccessTokenService
from nexus.authorization.bootstrap import ADMINISTRATOR_ROLE_NAME
from nexus.config.settings import Settings, load_settings
from nexus.errors import ErrorCode, NexusError
from nexus.infrastructure.authentication import JwtAccessTokenGateway
from nexus.infrastructure.persistence.models.auth_session import AuthSession
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.infrastructure.persistence.models.otp_challenge import OtpChallenge
from nexus.infrastructure.persistence.models.role import Role
from nexus.infrastructure.persistence.models.user import User
from nexus.infrastructure.persistence.models.user_role import UserRole
from nexus.infrastructure.persistence.repositories.authentication import (
    SqlAlchemyAuthenticationRepository,
)
from nexus.infrastructure.persistence.transaction import SqlAlchemyTransactionManager

BACKEND_ROOT = Path(__file__).resolve().parents[3]
SIGNUP_OTP = "123456"


def normalize_postgresql_driver(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    database_url = normalize_postgresql_driver(load_settings().database_url)
    database_name = f"nexus_signup_verify_test_{uuid.uuid4().hex}"
    test_url = make_url(database_url).set(database=database_name)
    admin_engine = create_engine(database_url, isolation_level="AUTOCOMMIT")

    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    except OperationalError:
        if os.environ.get("NEXUS_REQUIRE_POSTGRES_TESTS") == "true":
            raise
        pytest.skip("PostgreSQL is not available for signup verification tests")

    engine = create_engine(test_url)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["database_url"] = test_url.render_as_string(hide_password=False)
    command.upgrade(config, "head")

    try:
        yield engine
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = :database_name AND pid <> pg_backend_pid()
                    """
                ),
                {"database_name": database_name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin_engine.dispose()


def build_settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/15",
        cors_allowed_origins=["http://localhost:5173"],
        otp_hmac_secret="test-secret-value-with-enough-length",
        auth_token_secret="test-auth-token-secret-with-enough-length",
        refresh_token_secret="test-refresh-token-secret-with-enough-length",
        file_upload_context_key=("bmV4dXMtZGV2ZWxvcG1lbnQtdXBsb2FkLWtleS0wMDE"),
        signup_otp_ttl_seconds=600,
        signup_otp_max_attempts=5,
        signup_otp_length=6,
        signup_otp_rate_limit_window_seconds=900,
        signup_otp_rate_limit_max_requests=5,
        access_token_expires_seconds=900,
        refresh_token_expires_seconds=2_592_000,
        auth_token_issuer="nexus-test",
    )


@dataclass
class RecordingWelcomeEmailSender:
    sent: list[dict[str, str]] = field(default_factory=list)
    fail: bool = False

    async def send_signup_otp(
        self,
        *,
        email: str,
        otp: str,
        expires_at: datetime,
    ) -> None:
        del email, otp, expires_at

    async def send_welcome_email(self, *, email: str, display_name: str) -> None:
        if self.fail:
            raise AuthenticationEmailError("welcome email failed")
        self.sent.append({"email": email, "display_name": display_name})


class FailingAccessTokenGateway:
    expires_seconds = 900

    def issue_access_token(self, claims: AccessTokenClaims) -> str:
        del claims
        raise AccessTokenGatewayError("access token issuance failed")


class AllowingRateLimiter:
    async def allow(self, *, key: str, limit: int, window_seconds: int) -> bool:
        del key, limit, window_seconds
        return True


def build_service(
    session: AsyncSession,
    *,
    settings_value: Settings | None = None,
    welcome_sender: RecordingWelcomeEmailSender | None = None,
    access_token_gateway: AccessTokenGateway | None = None,
) -> SignupService:
    settings_value = settings_value or build_settings()
    transaction = SqlAlchemyTransactionManager(session)
    repository = SqlAlchemyAuthenticationRepository(session)
    resolved_access_token_gateway = access_token_gateway or JwtAccessTokenGateway(
        _access_token_service(settings_value)
    )
    return SignupService(
        policy=SignupPolicy(
            otp_hmac_secret=settings_value.otp_hmac_secret,
            signup_otp_length=settings_value.signup_otp_length,
            signup_otp_ttl_seconds=settings_value.signup_otp_ttl_seconds,
            signup_otp_max_attempts=settings_value.signup_otp_max_attempts,
            signup_otp_rate_limit_max_requests=(
                settings_value.signup_otp_rate_limit_max_requests
            ),
            signup_otp_rate_limit_window_seconds=(
                settings_value.signup_otp_rate_limit_window_seconds
            ),
        ),
        transaction=transaction,
        repository=repository,
        session_service=SessionService(
            policy=SessionPolicy(
                refresh_token_secret=settings_value.refresh_token_secret,
                refresh_token_expires_seconds=(
                    settings_value.refresh_token_expires_seconds
                ),
            ),
            transaction=transaction,
            repository=repository,
            access_token_gateway=resolved_access_token_gateway,
            clock=lambda: datetime.now(UTC),
        ),
        email_gateway=welcome_sender or RecordingWelcomeEmailSender(),
        rate_limiter=AllowingRateLimiter(),
        clock=lambda: datetime.now(UTC),
    )


async def complete_signup(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    request: SignupVerificationRequest | None = None,
    settings_value: Settings | None = None,
    welcome_sender: RecordingWelcomeEmailSender | None = None,
    access_token_gateway: AccessTokenGateway | None = None,
) -> SignupVerificationResult:
    async with session_factory() as session:
        return await build_service(
            session,
            settings_value=settings_value,
            welcome_sender=welcome_sender,
            access_token_gateway=access_token_gateway,
        ).complete_signup(request=request or signup_request())


def _access_token_service(settings_value: Settings) -> AccessTokenService:
    return AccessTokenService(
        secret=settings_value.auth_token_secret,
        expires_seconds=settings_value.access_token_expires_seconds,
        issuer=settings_value.auth_token_issuer,
        clock=lambda: datetime.now(UTC),
    )


def signup_request(**overrides: str) -> SignupVerificationRequest:
    values = {
        "email": "SUMMIYA@Acme.COM",
        "otp": SIGNUP_OTP,
        "organization_name": "  Acme AI  ",
        "first_name": "  Summiya  ",
        "last_name": "  Rasheed  ",
    }
    values.update(overrides)
    return SignupVerificationRequest(**values)


def create_signup_challenge(
    session: Session,
    *,
    settings_value: Settings,
    email: str = "summiya@acme.com",
    otp: str = SIGNUP_OTP,
    expires_at: datetime | None = None,
    attempt_count: int = 0,
    consumed_at: datetime | None = None,
    locked_at: datetime | None = None,
) -> OtpChallenge:
    challenge = OtpChallenge(
        user_id=None,
        email=email,
        purpose="signup",
        code_digest=digest_otp(
            secret=settings_value.otp_hmac_secret,
            email=email,
            purpose="signup",
            otp=otp,
        ),
        expires_at=expires_at or datetime.now(UTC) + timedelta(minutes=5),
        attempt_count=attempt_count,
        max_attempts=settings_value.signup_otp_max_attempts,
        consumed_at=consumed_at,
        locked_at=locked_at,
    )
    session.add(challenge)
    session.commit()
    return challenge


def test_valid_normalized_values_complete_signup(
    migrated_engine: Engine,
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings_value = build_settings()
    welcome_sender = RecordingWelcomeEmailSender()

    with Session(migrated_engine) as session:
        create_signup_challenge(session, settings_value=settings_value)
    result = asyncio.run(
        complete_signup(
            authentication_async_session_factory,
            settings_value=settings_value,
            welcome_sender=welcome_sender,
        )
    )

    with Session(migrated_engine) as session:
        organization = session.scalars(select(Organization)).one()
        user = session.scalars(select(User)).one()
        role = session.scalars(select(Role)).one()
        user_role = session.scalars(select(UserRole)).one()
        challenge = session.scalars(select(OtpChallenge)).one()
        auth_session = session.scalars(select(AuthSession)).one()

    token_context = AccessTokenService(
        secret=settings_value.auth_token_secret,
        expires_seconds=settings_value.access_token_expires_seconds,
        issuer=settings_value.auth_token_issuer,
    ).verify_access_token(result.access_token)

    assert result.status == "completed"
    assert result.refresh_token
    assert result.token_type == "bearer"
    assert result.expires_in == 900
    assert organization.name == "Acme AI"
    assert organization.slug == "acme-ai"
    assert user.email == "summiya@acme.com"
    assert user.display_name == "Summiya Rasheed"
    assert user.email_verified_at is not None
    assert role.name == ADMINISTRATOR_ROLE_NAME
    assert user_role.user_id == user.id
    assert user_role.role_id == role.id
    assert user_role.organization_id == organization.id
    assert challenge.consumed_at is not None
    assert auth_session.user_id == user.id
    assert token_context.user_public_id == user.public_id
    assert token_context.organization_public_id == organization.public_id
    assert token_context.session_public_id == auth_session.public_id
    assert welcome_sender.sent == [
        {"email": "summiya@acme.com", "display_name": "Summiya Rasheed"}
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("organization_name", "   "),
        ("first_name", "   "),
        ("last_name", "   "),
    ],
)
def test_blank_signup_profile_values_are_rejected(
    migrated_engine: Engine,
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
    field: str,
    value: str,
) -> None:
    settings_value = build_settings()

    with Session(migrated_engine) as session:
        create_signup_challenge(session, settings_value=settings_value)
    with pytest.raises(NexusError) as exc_info:
        asyncio.run(
            complete_signup(
                authentication_async_session_factory,
                settings_value=settings_value,
                request=signup_request(**{field: value}),
            )
        )

    assert exc_info.value.code == ErrorCode.VALIDATION_ERROR


def test_invalid_email_is_rejected(
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(NexusError) as exc_info:
        asyncio.run(
            complete_signup(
                authentication_async_session_factory,
                request=signup_request(email="not-an-email"),
            )
        )

    assert exc_info.value.code == ErrorCode.VALIDATION_ERROR


def test_existing_normalized_email_conflict_does_not_consume_otp_or_create_state(
    migrated_engine: Engine,
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings_value = build_settings()

    with Session(migrated_engine) as session:
        organization = Organization(name="Existing", slug="existing")
        user = User(
            organization=organization,
            email="summiya@acme.com",
            status="active",
        )
        session.add_all([organization, user])
        session.commit()
        create_signup_challenge(session, settings_value=settings_value)
    with pytest.raises(NexusError) as exc_info:
        asyncio.run(
            complete_signup(
                authentication_async_session_factory,
                settings_value=settings_value,
            )
        )

    assert exc_info.value.code == ErrorCode.CONFLICT

    with Session(migrated_engine) as session:
        challenge = session.scalars(select(OtpChallenge)).one()
        assert challenge.consumed_at is None
        assert session.scalar(select(func.count(Organization.id))) == 1
        assert session.scalar(select(func.count(User.id))) == 1
        assert session.scalar(select(func.count(UserRole.user_id))) == 0
        assert session.scalar(select(func.count(AuthSession.id))) == 0


def test_existing_organization_slug_returns_conflict(
    migrated_engine: Engine,
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings_value = build_settings()

    with Session(migrated_engine) as session:
        session.add(Organization(name="Acme AI", slug="acme-ai"))
        session.commit()
        create_signup_challenge(session, settings_value=settings_value)
    with pytest.raises(NexusError) as exc_info:
        asyncio.run(
            complete_signup(
                authentication_async_session_factory,
                settings_value=settings_value,
            )
        )

    assert exc_info.value.code == ErrorCode.CONFLICT


def test_wrong_otp_persists_attempt_count_without_creating_signup_state(
    migrated_engine: Engine,
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings_value = build_settings()

    with Session(migrated_engine) as session:
        create_signup_challenge(session, settings_value=settings_value)
    with pytest.raises(NexusError) as exc_info:
        asyncio.run(
            complete_signup(
                authentication_async_session_factory,
                settings_value=settings_value,
                request=signup_request(otp="000000"),
            )
        )

    assert exc_info.value.code == ErrorCode.UNAUTHORIZED

    with Session(migrated_engine) as session:
        challenge = session.scalars(select(OtpChallenge)).one()
        assert challenge.attempt_count == 1
        assert challenge.consumed_at is None
        assert session.scalar(select(func.count(Organization.id))) == 0
        assert session.scalar(select(func.count(User.id))) == 0
        assert session.scalar(select(func.count(AuthSession.id))) == 0


def test_max_attempt_failure_persists_locked_at(
    migrated_engine: Engine,
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings_value = build_settings()

    with Session(migrated_engine) as session:
        create_signup_challenge(
            session,
            settings_value=settings_value,
            attempt_count=settings_value.signup_otp_max_attempts - 1,
        )
    with pytest.raises(NexusError) as exc_info:
        asyncio.run(
            complete_signup(
                authentication_async_session_factory,
                settings_value=settings_value,
                request=signup_request(otp="000000"),
            )
        )

    assert exc_info.value.code == ErrorCode.UNAUTHORIZED

    with Session(migrated_engine) as session:
        challenge = session.scalars(select(OtpChallenge)).one()
        assert challenge.attempt_count == settings_value.signup_otp_max_attempts
        assert challenge.locked_at is not None
        assert challenge.consumed_at is None
        assert session.scalar(select(func.count(Organization.id))) == 0
        assert session.scalar(select(func.count(User.id))) == 0
        assert session.scalar(select(func.count(AuthSession.id))) == 0


def test_token_issuance_failure_rolls_back_partial_signup_state(
    migrated_engine: Engine,
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings_value = build_settings()

    with Session(migrated_engine) as session:
        create_signup_challenge(session, settings_value=settings_value)
    with pytest.raises(NexusError) as exc_info:
        asyncio.run(
            complete_signup(
                authentication_async_session_factory,
                settings_value=settings_value,
                access_token_gateway=FailingAccessTokenGateway(),
            )
        )

    assert exc_info.value.code == ErrorCode.SERVICE_UNAVAILABLE

    with Session(migrated_engine) as session:
        challenge = session.scalars(select(OtpChallenge)).one()
        assert challenge.attempt_count == 0
        assert challenge.consumed_at is None
        assert session.scalar(select(func.count(Organization.id))) == 0
        assert session.scalar(select(func.count(User.id))) == 0
        assert session.scalar(select(func.count(UserRole.user_id))) == 0
        assert session.scalar(select(func.count(AuthSession.id))) == 0


@pytest.mark.parametrize(
    "challenge_state",
    ["expired", "consumed", "locked", "missing"],
)
def test_non_mutating_otp_failures_roll_back_unrelated_pending_state(
    migrated_engine: Engine,
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
    challenge_state: str,
) -> None:
    settings_value = build_settings()

    with Session(migrated_engine) as session:
        if challenge_state == "expired":
            create_signup_challenge(
                session,
                settings_value=settings_value,
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        elif challenge_state == "consumed":
            create_signup_challenge(
                session,
                settings_value=settings_value,
                consumed_at=datetime.now(UTC),
            )
        elif challenge_state == "locked":
            create_signup_challenge(
                session,
                settings_value=settings_value,
                locked_at=datetime.now(UTC),
            )

    async def fail_signup() -> None:
        async with authentication_async_session_factory() as session:
            session.add(Organization(name="Pending", slug="pending"))
            await build_service(
                session,
                settings_value=settings_value,
            ).complete_signup(request=signup_request())

    with pytest.raises(NexusError) as exc_info:
        asyncio.run(fail_signup())

    assert exc_info.value.code == ErrorCode.UNAUTHORIZED

    with Session(migrated_engine) as session:
        assert session.scalar(select(func.count(Organization.id))) == 0
        assert session.scalar(select(func.count(User.id))) == 0
        assert session.scalar(select(func.count(AuthSession.id))) == 0
        challenge = session.scalar(select(OtpChallenge))
        if challenge is not None:
            assert challenge.attempt_count == 0


def test_welcome_email_failure_does_not_roll_back_signup(
    migrated_engine: Engine,
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings_value = build_settings()

    with Session(migrated_engine) as session:
        create_signup_challenge(session, settings_value=settings_value)
    result = asyncio.run(
        complete_signup(
            authentication_async_session_factory,
            settings_value=settings_value,
            welcome_sender=RecordingWelcomeEmailSender(fail=True),
        )
    )

    with Session(migrated_engine) as session:
        assert session.scalar(select(func.count(Organization.id))) == 1
        assert session.scalar(select(func.count(User.id))) == 1
        assert session.scalar(select(func.count(AuthSession.id))) == 1

    assert result.status == "completed"
