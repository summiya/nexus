from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from nexus.authentication.login_service import (
    LoginOtpRequest,
    LoginPolicy,
    LoginService,
)
from nexus.authentication.otp import digest_otp
from nexus.authentication.session_service import SessionService
from nexus.config.settings import load_settings
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.infrastructure.persistence.models.otp_challenge import OtpChallenge
from nexus.infrastructure.persistence.models.user import User
from nexus.infrastructure.persistence.repositories.authentication import (
    SqlAlchemyAuthenticationRepository,
)
from nexus.infrastructure.persistence.transaction import SqlAlchemyTransactionManager

BACKEND_ROOT = Path(__file__).resolve().parents[3]
OTP_SECRET = "test-secret-value-with-enough-length"


def normalize_postgresql_driver(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    database_url = normalize_postgresql_driver(load_settings().database_url)
    database_name = f"nexus_login_otp_test_{uuid.uuid4().hex}"
    test_url = make_url(database_url).set(database=database_name)
    admin_engine = create_engine(database_url, isolation_level="AUTOCOMMIT")

    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    except OperationalError:
        if os.environ.get("NEXUS_REQUIRE_POSTGRES_TESTS") == "true":
            raise
        pytest.skip("PostgreSQL is not available for login OTP integration tests")

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


@dataclass
class RecordingEmailGateway:
    sent: list[dict[str, Any]] = field(default_factory=list)

    def send_login_otp(
        self,
        *,
        email: str,
        otp: str,
        expires_at: datetime,
    ) -> None:
        self.sent.append({"email": email, "otp": otp, "expires_at": expires_at})

    def send_signup_otp(
        self,
        *,
        email: str,
        otp: str,
        expires_at: datetime,
    ) -> None:
        del email, otp, expires_at

    def send_welcome_email(self, *, email: str, display_name: str) -> None:
        del email, display_name


class AllowingRateLimiter:
    def allow(self, *, key: str, limit: int, window_seconds: int) -> bool:
        del key, limit, window_seconds
        return True


def build_service(
    session: Session,
    email_gateway: RecordingEmailGateway,
) -> LoginService:
    return LoginService(
        policy=LoginPolicy(
            otp_hmac_secret=OTP_SECRET,
            otp_length=6,
            otp_ttl_seconds=600,
            otp_max_attempts=5,
            otp_rate_limit_max_requests=5,
            otp_rate_limit_window_seconds=900,
        ),
        transaction=SqlAlchemyTransactionManager(session),
        repository=SqlAlchemyAuthenticationRepository(session),
        session_service=Mock(spec=SessionService),
        email_gateway=email_gateway,
        rate_limiter=AllowingRateLimiter(),
        clock=lambda: datetime(2026, 9, 22, 12, 0, tzinfo=UTC),
    )


def seed_registered_user(engine: Engine) -> None:
    with Session(engine) as session:
        organization = Organization(
            public_id=uuid.uuid4(),
            name="Acme",
            slug="acme",
            status="active",
        )
        session.add(organization)
        session.flush()
        session.add(
            User(
                public_id=uuid.uuid4(),
                organization_id=organization.id,
                email="user@example.com",
                display_name="Test User",
                status="active",
            )
        )
        session.commit()


def test_registered_email_persists_normalized_login_challenge(
    migrated_engine: Engine,
) -> None:
    seed_registered_user(migrated_engine)
    email_gateway = RecordingEmailGateway()

    with Session(migrated_engine) as session:
        build_service(session, email_gateway).request_login_otp(
            request=LoginOtpRequest(email="  USER@Example.COM ")
        )

    with Session(migrated_engine) as session:
        challenge = session.scalars(select(OtpChallenge)).one()

    sent = email_gateway.sent[0]
    assert challenge.email == "user@example.com"
    assert challenge.purpose == "login"
    assert challenge.user_id is None
    assert challenge.max_attempts == 5
    assert challenge.code_digest == digest_otp(
        secret=OTP_SECRET,
        email="user@example.com",
        purpose="login",
        otp=sent["otp"],
    )
    assert challenge.code_digest != sent["otp"]
    assert sent["otp"] not in challenge.code_digest


def test_unknown_email_persists_nothing_and_sends_nothing(
    migrated_engine: Engine,
) -> None:
    email_gateway = RecordingEmailGateway()

    with Session(migrated_engine) as session:
        build_service(session, email_gateway).request_login_otp(
            request=LoginOtpRequest(email="unknown@example.com")
        )

    with Session(migrated_engine) as session:
        challenges = tuple(session.scalars(select(OtpChallenge)))

    assert challenges == ()
    assert email_gateway.sent == []
