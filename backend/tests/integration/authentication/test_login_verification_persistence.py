from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
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
)
from nexus.authentication.login_service import (
    LoginPolicy,
    LoginService,
    LoginVerificationRequest,
)
from nexus.authentication.otp import digest_otp
from nexus.authentication.repository import AuthenticationIdentity
from nexus.authentication.repository import OtpChallenge as OtpChallengeRecord
from nexus.authentication.session_service import (
    SessionPolicy,
    SessionService,
    SessionTokenResult,
)
from nexus.authentication.tokens import AccessTokenService
from nexus.config.settings import load_settings
from nexus.errors import ErrorCode, NexusError
from nexus.infrastructure.authentication import JwtAccessTokenGateway
from nexus.infrastructure.persistence.models.auth_session import AuthSession
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.infrastructure.persistence.models.otp_challenge import (
    OtpChallenge as OtpChallengeModel,
)
from nexus.infrastructure.persistence.models.user import User
from nexus.infrastructure.persistence.repositories.authentication import (
    SqlAlchemyAuthenticationRepository,
)
from nexus.infrastructure.persistence.transaction import SqlAlchemyTransactionManager

BACKEND_ROOT = Path(__file__).resolve().parents[3]
# PyJWT validates ``iat`` against the real process clock, so keep the integration
# test clock aligned with the runtime instead of using a potentially future date.
NOW = datetime.now(UTC)
EMAIL = "user@example.com"
LOGIN_OTP = "123456"
OTP_SECRET = "test-secret-value-with-enough-length"
ACCESS_TOKEN_SECRET = "test-access-token-secret-with-enough-length"
REFRESH_TOKEN_SECRET = "test-refresh-token-secret-with-enough-length"


def normalize_postgresql_driver(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    database_url = normalize_postgresql_driver(load_settings().database_url)
    database_name = f"nexus_login_verify_test_{uuid.uuid4().hex}"
    test_url = make_url(database_url).set(database=database_name)
    admin_engine = create_engine(database_url, isolation_level="AUTOCOMMIT")

    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    except OperationalError:
        if os.environ.get("NEXUS_REQUIRE_POSTGRES_TESTS") == "true":
            raise
        pytest.skip("PostgreSQL is not available for login verification tests")

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


@dataclass(frozen=True)
class SeededIdentity:
    user_public_id: uuid.UUID
    organization_public_id: uuid.UUID


class FailingAccessTokenGateway:
    expires_seconds = 900

    def issue_access_token(self, claims: AccessTokenClaims) -> str:
        del claims
        raise AccessTokenGatewayError("access token issuance failed")


class PausingAuthenticationRepository(SqlAlchemyAuthenticationRepository):
    def __init__(
        self,
        session: AsyncSession,
        *,
        lock_acquired: asyncio.Event | None = None,
        release_lock: asyncio.Event | None = None,
        query_started: asyncio.Event | None = None,
    ) -> None:
        super().__init__(session)
        self._lock_acquired = lock_acquired
        self._release_lock = release_lock
        self._query_started = query_started

    async def get_latest_otp_challenge_for_update(
        self,
        *,
        email: str,
        purpose: str,
    ) -> OtpChallengeRecord | None:
        if self._query_started is not None:
            self._query_started.set()
        challenge = await super().get_latest_otp_challenge_for_update(
            email=email,
            purpose=purpose,
        )
        if self._lock_acquired is not None:
            self._lock_acquired.set()
            if self._release_lock is None:
                raise TimeoutError("Missing OTP challenge lock release event")
            await asyncio.wait_for(self._release_lock.wait(), timeout=10)
        return challenge


def access_token_service() -> AccessTokenService:
    return AccessTokenService(
        secret=ACCESS_TOKEN_SECRET,
        expires_seconds=900,
        issuer="nexus-test",
        clock=lambda: NOW,
    )


def build_service(
    session: AsyncSession,
    *,
    repository: SqlAlchemyAuthenticationRepository | None = None,
    access_token_gateway: AccessTokenGateway | None = None,
) -> LoginService:
    transaction = SqlAlchemyTransactionManager(session)
    resolved_repository = repository or SqlAlchemyAuthenticationRepository(session)
    resolved_access_token_gateway = access_token_gateway or JwtAccessTokenGateway(
        access_token_service()
    )
    return LoginService(
        policy=LoginPolicy(
            otp_hmac_secret=OTP_SECRET,
            otp_length=6,
            otp_ttl_seconds=600,
            otp_max_attempts=5,
            otp_rate_limit_max_requests=5,
            otp_rate_limit_window_seconds=900,
        ),
        transaction=transaction,
        repository=resolved_repository,
        session_service=SessionService(
            policy=SessionPolicy(
                refresh_token_secret=REFRESH_TOKEN_SECRET,
                refresh_token_expires_seconds=2_592_000,
            ),
            transaction=transaction,
            repository=resolved_repository,
            access_token_gateway=resolved_access_token_gateway,
            clock=lambda: NOW,
        ),
        email_gateway=None,  # type: ignore[arg-type]
        rate_limiter=None,  # type: ignore[arg-type]
        clock=lambda: NOW,
    )


async def verify_login_otp(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    request: LoginVerificationRequest | None = None,
    access_token_gateway: AccessTokenGateway | None = None,
) -> SessionTokenResult:
    async with session_factory() as session:
        return await build_service(
            session,
            access_token_gateway=access_token_gateway,
        ).verify_login_otp(request=request or verification_request())


def seed_identity(
    engine: Engine,
    *,
    user_status: str = "active",
    user_deleted_at: datetime | None = None,
    organization_status: str = "active",
    organization_deleted_at: datetime | None = None,
) -> SeededIdentity:
    organization_public_id = uuid.uuid4()
    user_public_id = uuid.uuid4()
    with Session(engine) as session:
        organization = Organization(
            public_id=organization_public_id,
            name="Acme",
            slug=f"acme-{uuid.uuid4().hex}",
            status=organization_status,
            deleted_at=organization_deleted_at,
        )
        session.add(organization)
        session.flush()
        session.add(
            User(
                public_id=user_public_id,
                organization_id=organization.id,
                email=EMAIL,
                display_name="Test User",
                status=user_status,
                email_verified_at=NOW,
                deleted_at=user_deleted_at,
            )
        )
        session.commit()
    return SeededIdentity(
        user_public_id=user_public_id,
        organization_public_id=organization_public_id,
    )


def seed_challenge(
    engine: Engine,
    *,
    purpose: str = "login",
    attempt_count: int = 0,
) -> uuid.UUID:
    challenge_id = uuid.uuid4()
    with Session(engine) as session:
        session.add(
            OtpChallengeModel(
                id=challenge_id,
                user_id=None,
                email=EMAIL,
                purpose=purpose,
                code_digest=digest_otp(
                    secret=OTP_SECRET,
                    email=EMAIL,
                    purpose=purpose,
                    otp=LOGIN_OTP,
                ),
                expires_at=NOW + timedelta(minutes=5),
                attempt_count=attempt_count,
                max_attempts=5,
            )
        )
        session.commit()
    return challenge_id


def verification_request(*, otp: str = LOGIN_OTP) -> LoginVerificationRequest:
    return LoginVerificationRequest(email=EMAIL, otp=otp)


def assert_generic_unauthorized(exc: NexusError) -> None:
    assert exc.code == ErrorCode.UNAUTHORIZED
    assert exc.message == "Authentication credentials are invalid."


def test_successful_verification_consumes_otp_and_creates_one_session(
    migrated_engine: Engine,
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    identity = seed_identity(migrated_engine)
    challenge_id = seed_challenge(migrated_engine)

    result = asyncio.run(verify_login_otp(authentication_async_session_factory))

    with Session(migrated_engine) as session:
        challenge = session.get(OtpChallengeModel, challenge_id)
        auth_session = session.scalars(select(AuthSession)).one()
        assert challenge is not None
        consumed_at = challenge.consumed_at
        auth_session_user_public_id = auth_session.user.public_id
        stored_refresh_token_hash = auth_session.refresh_token_hash
        auth_session_public_id = auth_session.public_id

    token_context = access_token_service().verify_access_token(result.access_token)
    assert consumed_at == NOW
    assert auth_session_user_public_id == identity.user_public_id
    assert stored_refresh_token_hash != result.refresh_token
    assert result.token_type == "bearer"
    assert result.expires_in == 900
    assert token_context.user_public_id == identity.user_public_id
    assert token_context.organization_public_id == identity.organization_public_id
    assert token_context.session_public_id == auth_session_public_id


def test_signup_challenge_cannot_authenticate_login(
    migrated_engine: Engine,
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seed_identity(migrated_engine)
    challenge_id = seed_challenge(migrated_engine, purpose="signup")

    with pytest.raises(NexusError) as exc_info:
        asyncio.run(verify_login_otp(authentication_async_session_factory))

    assert_generic_unauthorized(exc_info.value)
    with Session(migrated_engine) as session:
        challenge = session.get(OtpChallengeModel, challenge_id)
        assert challenge is not None
        assert challenge.consumed_at is None
        assert session.scalar(select(func.count(AuthSession.id))) == 0


def test_wrong_otp_persists_attempt_and_final_attempt_locks_challenge(
    migrated_engine: Engine,
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seed_identity(migrated_engine)
    challenge_id = seed_challenge(migrated_engine, attempt_count=4)

    with pytest.raises(NexusError) as exc_info:
        asyncio.run(
            verify_login_otp(
                authentication_async_session_factory,
                request=verification_request(otp="654321"),
            )
        )

    assert_generic_unauthorized(exc_info.value)
    with Session(migrated_engine) as session:
        challenge = session.get(OtpChallengeModel, challenge_id)
        assert challenge is not None
        assert challenge.attempt_count == 5
        assert challenge.locked_at == NOW
        assert challenge.consumed_at is None
        assert session.scalar(select(func.count(AuthSession.id))) == 0


@pytest.mark.parametrize(
    (
        "user_status",
        "user_deleted_at",
        "organization_status",
        "organization_deleted_at",
    ),
    [
        ("inactive", None, "active", None),
        ("active", NOW, "active", None),
        ("active", None, "inactive", None),
        ("active", None, "active", NOW),
    ],
    ids=[
        "inactive-user",
        "deleted-user",
        "inactive-organization",
        "deleted-organization",
    ],
)
def test_ineligible_identity_returns_generic_unauthorized(
    migrated_engine: Engine,
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
    user_status: str,
    user_deleted_at: datetime | None,
    organization_status: str,
    organization_deleted_at: datetime | None,
) -> None:
    seed_identity(
        migrated_engine,
        user_status=user_status,
        user_deleted_at=user_deleted_at,
        organization_status=organization_status,
        organization_deleted_at=organization_deleted_at,
    )
    challenge_id = seed_challenge(migrated_engine)

    with pytest.raises(NexusError) as exc_info:
        asyncio.run(verify_login_otp(authentication_async_session_factory))

    assert_generic_unauthorized(exc_info.value)
    with Session(migrated_engine) as session:
        challenge = session.get(OtpChallengeModel, challenge_id)
        assert challenge is not None
        assert challenge.consumed_at is None
        assert session.scalar(select(func.count(AuthSession.id))) == 0


def test_identity_lookup_returns_only_public_identity(
    migrated_engine: Engine,
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = seed_identity(migrated_engine)

    async def get_identity() -> AuthenticationIdentity | None:
        async with authentication_async_session_factory() as session:
            return await SqlAlchemyAuthenticationRepository(
                session
            ).get_identity_by_email(EMAIL)

    identity = asyncio.run(get_identity())

    assert identity == AuthenticationIdentity(
        user_public_id=seeded.user_public_id,
        organization_public_id=seeded.organization_public_id,
    )
    assert identity is not None
    assert set(identity.__dict__) == {
        "user_public_id",
        "organization_public_id",
    }


def test_consumed_otp_cannot_create_a_second_session(
    migrated_engine: Engine,
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seed_identity(migrated_engine)
    seed_challenge(migrated_engine)

    async def verify_twice() -> None:
        async with authentication_async_session_factory() as session:
            service = build_service(session)
            await service.verify_login_otp(request=verification_request())
            await service.verify_login_otp(request=verification_request())

    with pytest.raises(NexusError) as exc_info:
        asyncio.run(verify_twice())

    assert_generic_unauthorized(exc_info.value)
    with Session(migrated_engine) as session:
        assert session.scalar(select(func.count(AuthSession.id))) == 1


def test_token_issuance_failure_rolls_back_otp_and_session(
    migrated_engine: Engine,
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seed_identity(migrated_engine)
    challenge_id = seed_challenge(migrated_engine)

    with pytest.raises(NexusError) as exc_info:
        asyncio.run(
            verify_login_otp(
                authentication_async_session_factory,
                access_token_gateway=FailingAccessTokenGateway(),
            )
        )

    assert exc_info.value.code == ErrorCode.SERVICE_UNAVAILABLE
    with Session(migrated_engine) as session:
        challenge = session.get(OtpChallengeModel, challenge_id)
        assert challenge is not None
        assert challenge.consumed_at is None
        assert session.scalar(select(func.count(AuthSession.id))) == 0


def test_concurrent_verification_creates_exactly_one_session(
    migrated_engine: Engine,
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seed_identity(migrated_engine)
    seed_challenge(migrated_engine)

    async def verify_concurrently() -> set[str | ErrorCode]:
        lock_acquired = asyncio.Event()
        release_lock = asyncio.Event()
        competing_query_started = asyncio.Event()

        async def verify(*, pause_with_lock: bool) -> str | ErrorCode:
            async with authentication_async_session_factory() as session:
                repository = PausingAuthenticationRepository(
                    session,
                    lock_acquired=lock_acquired if pause_with_lock else None,
                    release_lock=release_lock if pause_with_lock else None,
                    query_started=(
                        None if pause_with_lock else competing_query_started
                    ),
                )
                try:
                    await build_service(
                        session,
                        repository=repository,
                    ).verify_login_otp(request=verification_request())
                except NexusError as exc:
                    return exc.code
                return "completed"

        first = asyncio.create_task(verify(pause_with_lock=True))
        await asyncio.wait_for(lock_acquired.wait(), timeout=10)
        second = asyncio.create_task(verify(pause_with_lock=False))
        await asyncio.wait_for(competing_query_started.wait(), timeout=10)
        assert not second.done()
        release_lock.set()
        return set(await asyncio.wait_for(asyncio.gather(first, second), timeout=10))

    outcomes = asyncio.run(verify_concurrently())

    assert outcomes == {"completed", ErrorCode.UNAUTHORIZED}
    with Session(migrated_engine) as session:
        challenge = session.scalars(select(OtpChallengeModel)).one()
        assert challenge.consumed_at is not None
        assert session.scalar(select(func.count(AuthSession.id))) == 1
