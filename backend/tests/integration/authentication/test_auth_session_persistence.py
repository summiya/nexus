from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from nexus.config.settings import settings
from nexus.errors import ErrorCode, NexusError
from nexus.infrastructure.persistence.models.auth_session import AuthSession
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.infrastructure.persistence.models.user import User
from nexus.infrastructure.persistence.repositories.auth_session import (
    SqlAlchemyAuthSessionRepository,
)
from nexus.security.authentication_tokens import (
    AccessTokenError,
    AccessTokenService,
    AuthTokenContext,
)
from nexus.services.authentication_session import AuthenticationSessionService

BACKEND_ROOT = Path(__file__).resolve().parents[3]


class FailingAccessTokenService(AccessTokenService):
    def issue_access_token(self, context: AuthTokenContext) -> str:
        raise AccessTokenError("access token issuance failed")


def normalize_postgresql_driver(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    database_url = normalize_postgresql_driver(settings.database_url)
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


def build_service(session: Session) -> AuthenticationSessionService:
    return AuthenticationSessionService(
        access_token_service=AccessTokenService(
            secret="test-auth-token-secret-with-enough-length",
            expires_seconds=900,
            issuer="nexus-test",
            clock=lambda: datetime(2026, 9, 16, tzinfo=UTC),
        ),
        refresh_token_secret="test-refresh-token-secret-with-enough-length",
        refresh_token_expires_seconds=2_592_000,
        auth_session_repository=SqlAlchemyAuthSessionRepository(session),
        clock=lambda: datetime(2026, 9, 16, tzinfo=UTC),
    )


def build_failing_service(session: Session) -> AuthenticationSessionService:
    return AuthenticationSessionService(
        access_token_service=FailingAccessTokenService(
            secret="test-auth-token-secret-with-enough-length",
            expires_seconds=900,
            issuer="nexus-test",
            clock=lambda: datetime(2026, 9, 16, tzinfo=UTC),
        ),
        refresh_token_secret="test-refresh-token-secret-with-enough-length",
        refresh_token_expires_seconds=2_592_000,
        auth_session_repository=SqlAlchemyAuthSessionRepository(session),
        clock=lambda: datetime(2026, 9, 16, tzinfo=UTC),
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
        result = auth_service.create_session(user=user)
        session.commit()

    with Session(migrated_engine) as session:
        auth_session = session.scalars(select(AuthSession)).one()
        assert auth_session.refresh_token_hash != result.refresh_token
        assert result.refresh_token not in auth_session.refresh_token_hash
        assert auth_session.user.email == "person@example.com"


def test_refresh_rotates_token_and_invalidates_old_token(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        auth_service = build_service(session)
        user = create_user(session)
        first = auth_service.create_session(user=user)
        session.commit()

    with Session(migrated_engine) as session:
        auth_service = build_service(session)
        second = auth_service.refresh_session(
            refresh_token=first.refresh_token,
        )
        session.commit()

    assert second.refresh_token != first.refresh_token

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


def test_revoke_persists_revoked_at(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        auth_service = build_service(session)
        user = create_user(session)
        result = auth_service.create_session(user=user)
        session.commit()

    with Session(migrated_engine) as session:
        auth_service = build_service(session)
        auth_service.revoke_session(refresh_token=result.refresh_token)
        session.commit()

    with Session(migrated_engine) as session:
        auth_session = session.scalars(select(AuthSession)).one()
        assert auth_session.revoked_at == datetime(2026, 9, 16, tzinfo=UTC)


def test_outer_rollback_removes_created_session(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        auth_service = build_service(session)
        user = create_user(session)
        auth_service.create_session(user=user)
        session.rollback()

    with Session(migrated_engine) as session:
        assert session.scalar(select(func.count(AuthSession.id))) == 0


def test_create_session_token_failure_rolls_back_persisted_session(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        auth_service = build_failing_service(session)
        user = create_user(session)
        with pytest.raises(NexusError) as exc_info:
            auth_service.create_session(user=user)

        assert exc_info.value.code == ErrorCode.SERVICE_UNAVAILABLE
        session.rollback()

    with Session(migrated_engine) as session:
        assert session.scalar(select(func.count(AuthSession.id))) == 0


def test_refresh_session_token_failure_rolls_back_rotation(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        auth_service = build_service(session)
        user = create_user(session)
        first = auth_service.create_session(user=user)
        session.commit()

    original_hash = auth_service._hash_refresh_token(first.refresh_token)

    with Session(migrated_engine) as session:
        failing_service = build_failing_service(session)
        with pytest.raises(NexusError) as exc_info:
            failing_service.refresh_session(
                refresh_token=first.refresh_token,
            )

        assert exc_info.value.code == ErrorCode.SERVICE_UNAVAILABLE
        session.rollback()

    with Session(migrated_engine) as session:
        auth_session = session.scalars(select(AuthSession)).one()
        assert auth_session.refresh_token_hash == original_hash
        assert auth_session.last_used_at is None

    with Session(migrated_engine) as session:
        auth_service = build_service(session)
        refreshed = auth_service.refresh_session(
            refresh_token=first.refresh_token,
        )
        session.commit()

    assert refreshed.refresh_token != first.refresh_token
