from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from nexus.authentication.repository import (
    AuthenticationIdentity,
    AuthenticationSession,
)
from nexus.authentication.session_service import (
    SessionPolicy,
    SessionService,
)
from nexus.authentication.tokens import (
    AccessTokenError,
    AccessTokenService,
    AuthTokenContext,
)
from nexus.config.settings import load_settings
from nexus.errors import ErrorCode, NexusError
from nexus.infrastructure.authentication import JwtAccessTokenGateway
from nexus.infrastructure.persistence.models.auth_session import AuthSession
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.infrastructure.persistence.models.user import User
from nexus.infrastructure.persistence.repositories.authentication import (
    SqlAlchemyAuthenticationRepository,
)
from nexus.infrastructure.persistence.transaction import SqlAlchemyTransactionManager

BACKEND_ROOT = Path(__file__).resolve().parents[3]


class FailingAccessTokenService(AccessTokenService):
    def issue_access_token(self, context: AuthTokenContext) -> str:
        raise AccessTokenError("access token issuance failed")


class FailingAfterSessionUpdateRepository(SqlAlchemyAuthenticationRepository):
    def update_session(self, session: AuthenticationSession) -> None:
        super().update_session(session)
        raise RuntimeError("session persistence failed")


class PausingAuthenticationRepository(SqlAlchemyAuthenticationRepository):
    def __init__(
        self,
        session: Session,
        *,
        lock_acquired: Event | None = None,
        release_lock: Event | None = None,
        query_started: Event | None = None,
    ) -> None:
        super().__init__(session)
        self._lock_acquired = lock_acquired
        self._release_lock = release_lock
        self._query_started = query_started

    def get_session_by_refresh_token_hash_for_update(
        self,
        refresh_token_hash: str,
    ) -> AuthenticationSession | None:
        if self._query_started is not None:
            self._query_started.set()
        session = super().get_session_by_refresh_token_hash_for_update(
            refresh_token_hash
        )
        if self._lock_acquired is not None:
            self._lock_acquired.set()
            if self._release_lock is None or not self._release_lock.wait(timeout=10):
                raise TimeoutError("Timed out waiting to release auth session lock")
        return session


def normalize_postgresql_driver(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    database_url = normalize_postgresql_driver(load_settings().database_url)
    database_name = f"nexus_auth_session_test_{uuid.uuid4().hex}"
    test_url = make_url(database_url).set(database=database_name)
    admin_engine = create_engine(database_url, isolation_level="AUTOCOMMIT")

    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    except OperationalError:
        if os.environ.get("NEXUS_REQUIRE_POSTGRES_TESTS") == "true":
            raise
        pytest.skip("PostgreSQL is not available for auth session tests")

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


def build_service(
    session: Session,
    *,
    repository: SqlAlchemyAuthenticationRepository | None = None,
) -> SessionService:
    return _build_service(
        session,
        AccessTokenService(
            secret="test-auth-token-secret-with-enough-length",
            expires_seconds=900,
            issuer="nexus-test",
            clock=lambda: datetime(2026, 9, 16, tzinfo=UTC),
        ),
        repository=repository,
    )


def build_failing_service(session: Session) -> SessionService:
    return _build_service(
        session,
        FailingAccessTokenService(
            secret="test-auth-token-secret-with-enough-length",
            expires_seconds=900,
            issuer="nexus-test",
            clock=lambda: datetime(2026, 9, 16, tzinfo=UTC),
        ),
    )


def _build_service(
    session: Session,
    token_service: AccessTokenService,
    *,
    repository: SqlAlchemyAuthenticationRepository | None = None,
) -> SessionService:
    return SessionService(
        policy=SessionPolicy(
            refresh_token_secret="test-refresh-token-secret-with-enough-length",
            refresh_token_expires_seconds=2_592_000,
        ),
        transaction=SqlAlchemyTransactionManager(session),
        repository=repository or SqlAlchemyAuthenticationRepository(session),
        access_token_gateway=JwtAccessTokenGateway(token_service),
        clock=lambda: datetime(2026, 9, 16, tzinfo=UTC),
    )


def identity_for(user: User) -> AuthenticationIdentity:
    return AuthenticationIdentity(
        user_public_id=user.public_id,
        organization_public_id=user.organization.public_id,
    )


def create_user(session: Session) -> User:
    organization = Organization(name="Acme", slug="acme", status="active")
    user = User(
        organization=organization,
        email="person@example.com",
        status="active",
    )
    session.add_all([organization, user])
    session.flush()
    return user


def test_create_session_persists_hash_without_plaintext(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        auth_service = build_service(session)
        user = create_user(session)
        result = auth_service.create_session(identity=identity_for(user))

    with Session(migrated_engine) as session:
        auth_session = session.scalars(select(AuthSession)).one()
        assert auth_session.refresh_token_hash != result.refresh_token
        assert result.refresh_token not in auth_session.refresh_token_hash
        assert auth_session.user.email == "person@example.com"


def test_refresh_rotates_token_invalidates_old_token_and_allows_next_rotation(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        auth_service = build_service(session)
        user = create_user(session)
        first = auth_service.create_session(identity=identity_for(user))

    with Session(migrated_engine) as session:
        auth_service = build_service(session)
        second = auth_service.refresh_session(
            refresh_token=first.refresh_token,
        )

    assert second.refresh_token != first.refresh_token
    assert second.access_token

    with Session(migrated_engine) as session, pytest.raises(NexusError) as exc_info:
        build_service(session).refresh_session(refresh_token=first.refresh_token)

    assert exc_info.value.code == ErrorCode.UNAUTHORIZED
    assert exc_info.value.message == "Authentication credentials are invalid."

    with Session(migrated_engine) as session:
        third = build_service(session).refresh_session(
            refresh_token=second.refresh_token,
        )

    assert third.refresh_token not in {first.refresh_token, second.refresh_token}

    with Session(migrated_engine) as session:
        assert (
            session.scalar(
                select(func.count(AuthSession.id)).where(
                    AuthSession.refresh_token_hash
                    == auth_service._hash_refresh_token(first.refresh_token)
                )
            )
            == 0
        )
        auth_session = session.scalars(select(AuthSession)).one()
        assert auth_session.last_used_at == datetime(2026, 9, 16, tzinfo=UTC)
        assert auth_session.refresh_token_hash == auth_service._hash_refresh_token(
            third.refresh_token
        )


def test_revoke_persists_revoked_at(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        auth_service = build_service(session)
        user = create_user(session)
        result = auth_service.create_session(identity=identity_for(user))

    with Session(migrated_engine) as session:
        auth_service = build_service(session)
        auth_service.revoke_session(refresh_token=result.refresh_token)

    with Session(migrated_engine) as session:
        auth_session = session.scalars(select(AuthSession)).one()
        assert auth_session.revoked_at == datetime(2026, 9, 16, tzinfo=UTC)


def test_create_session_owns_commit(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        auth_service = build_service(session)
        user = create_user(session)
        auth_service.create_session(identity=identity_for(user))
        session.rollback()

    with Session(migrated_engine) as session:
        assert session.scalar(select(func.count(AuthSession.id))) == 1


def test_create_session_token_failure_rolls_back_persisted_session(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        auth_service = build_failing_service(session)
        user = create_user(session)
        with pytest.raises(NexusError) as exc_info:
            auth_service.create_session(identity=identity_for(user))

        assert exc_info.value.code == ErrorCode.SERVICE_UNAVAILABLE

    with Session(migrated_engine) as session:
        assert session.scalar(select(func.count(AuthSession.id))) == 0


def test_refresh_session_token_failure_rolls_back_rotation(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        auth_service = build_service(session)
        user = create_user(session)
        first = auth_service.create_session(identity=identity_for(user))

    original_hash = auth_service._hash_refresh_token(first.refresh_token)

    with Session(migrated_engine) as session:
        failing_service = build_failing_service(session)
        with pytest.raises(NexusError) as exc_info:
            failing_service.refresh_session(
                refresh_token=first.refresh_token,
            )

        assert exc_info.value.code == ErrorCode.SERVICE_UNAVAILABLE

    with Session(migrated_engine) as session:
        auth_session = session.scalars(select(AuthSession)).one()
        assert auth_session.refresh_token_hash == original_hash
        assert auth_session.last_used_at is None

    with Session(migrated_engine) as session:
        auth_service = build_service(session)
        refreshed = auth_service.refresh_session(
            refresh_token=first.refresh_token,
        )

    assert refreshed.refresh_token != first.refresh_token


def test_refresh_persistence_failure_rolls_back_and_keeps_old_token_usable(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        auth_service = build_service(session)
        user = create_user(session)
        first = auth_service.create_session(identity=identity_for(user))

    original_hash = auth_service._hash_refresh_token(first.refresh_token)

    with Session(migrated_engine) as session:
        repository = FailingAfterSessionUpdateRepository(session)
        with pytest.raises(RuntimeError, match="session persistence failed"):
            build_service(session, repository=repository).refresh_session(
                refresh_token=first.refresh_token,
            )

    with Session(migrated_engine) as session:
        auth_session = session.scalars(select(AuthSession)).one()
        assert auth_session.refresh_token_hash == original_hash
        assert auth_session.last_used_at is None

    with Session(migrated_engine) as session:
        refreshed = build_service(session).refresh_session(
            refresh_token=first.refresh_token,
        )

    assert refreshed.refresh_token != first.refresh_token


@pytest.mark.parametrize(
    "identity_state",
    [
        "inactive-user",
        "deleted-user",
        "inactive-organization",
        "deleted-organization",
    ],
)
def test_ineligible_identity_cannot_refresh_session(
    migrated_engine: Engine,
    identity_state: str,
) -> None:
    with Session(migrated_engine) as session:
        auth_service = build_service(session)
        user = create_user(session)
        first = auth_service.create_session(identity=identity_for(user))

    original_hash = auth_service._hash_refresh_token(first.refresh_token)
    with Session(migrated_engine) as session:
        user = session.scalars(select(User)).one()
        organization = session.scalars(select(Organization)).one()
        if identity_state == "inactive-user":
            user.status = "inactive"
        elif identity_state == "deleted-user":
            user.deleted_at = datetime(2026, 9, 16, tzinfo=UTC)
        elif identity_state == "inactive-organization":
            organization.status = "inactive"
        else:
            organization.deleted_at = datetime(2026, 9, 16, tzinfo=UTC)
        session.commit()

    with Session(migrated_engine) as session, pytest.raises(NexusError) as exc_info:
        build_service(session).refresh_session(refresh_token=first.refresh_token)

    assert exc_info.value.code == ErrorCode.UNAUTHORIZED
    assert exc_info.value.message == "Authentication credentials are invalid."
    with Session(migrated_engine) as session:
        auth_session = session.scalars(select(AuthSession)).one()
        assert auth_session.refresh_token_hash == original_hash
        assert auth_session.last_used_at is None


def test_concurrent_refresh_allows_exactly_one_rotation(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        auth_service = build_service(session)
        user = create_user(session)
        first = auth_service.create_session(identity=identity_for(user))

    lock_acquired = Event()
    release_lock = Event()
    competing_query_started = Event()

    def refresh(*, pause_with_lock: bool) -> str:
        with Session(migrated_engine) as session:
            repository = PausingAuthenticationRepository(
                session,
                lock_acquired=lock_acquired if pause_with_lock else None,
                release_lock=release_lock if pause_with_lock else None,
                query_started=(None if pause_with_lock else competing_query_started),
            )
            try:
                result = build_service(
                    session,
                    repository=repository,
                ).refresh_session(refresh_token=first.refresh_token)
            except NexusError as exc:
                assert exc.code == ErrorCode.UNAUTHORIZED
                return "unauthorized"
            return result.refresh_token

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_attempt = executor.submit(refresh, pause_with_lock=True)
        assert lock_acquired.wait(timeout=10)
        second_attempt = executor.submit(refresh, pause_with_lock=False)
        assert competing_query_started.wait(timeout=10)
        assert not second_attempt.done()
        release_lock.set()
        outcomes = [
            first_attempt.result(timeout=10),
            second_attempt.result(timeout=10),
        ]

    assert outcomes.count("unauthorized") == 1
    winning_refresh_tokens = [
        outcome for outcome in outcomes if outcome != "unauthorized"
    ]
    assert len(winning_refresh_tokens) == 1
    with Session(migrated_engine) as session:
        auth_session = session.scalars(select(AuthSession)).one()
        assert auth_session.refresh_token_hash == auth_service._hash_refresh_token(
            winning_refresh_tokens[0]
        )
