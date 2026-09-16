from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from nexus.application.authentication.signup import SignupOtpRequest, SignupOtpService
from nexus.config.settings import Settings, settings
from nexus.infrastructure.persistence.models.otp_challenge import OtpChallenge

BACKEND_ROOT = Path(__file__).resolve().parents[3]


def normalize_postgresql_driver(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    database_url = normalize_postgresql_driver(settings.database_url)
    database_name = f"nexus_signup_otp_test_{uuid.uuid4().hex}"
    test_url = make_url(database_url).set(database=database_name)
    admin_engine = create_engine(database_url, isolation_level="AUTOCOMMIT")

    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    except OperationalError:
        if os.environ.get("NEXUS_REQUIRE_POSTGRES_TESTS") == "true":
            raise
        pytest.skip("PostgreSQL is not available for signup integration tests")

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
        signup_otp_ttl_seconds=600,
        signup_otp_max_attempts=5,
        signup_otp_length=6,
        signup_otp_rate_limit_window_seconds=900,
        signup_otp_rate_limit_max_requests=5,
    )


@dataclass
class FakeEmailProvider:
    sent: list[dict[str, Any]] = field(default_factory=list)

    def send_signup_otp(
        self,
        *,
        email: str,
        otp: str,
        expires_at: datetime,
    ) -> None:
        self.sent.append({"email": email, "otp": otp, "expires_at": expires_at})


class AllowingRateLimiter:
    def allow(self, *, key: str, limit: int, window_seconds: int) -> bool:
        del key, limit, window_seconds
        return True


def test_signup_request_persists_secure_otp_challenge(
    migrated_engine: Engine,
) -> None:
    email_provider = FakeEmailProvider()
    service = SignupOtpService(
        settings=build_settings(),
        email_sender=email_provider,
        rate_limiter=AllowingRateLimiter(),
    )

    with Session(migrated_engine) as session:
        service.request_signup_otp(
            session=session,
            request=SignupOtpRequest(
                organization_name="Acme AI",
                first_name="Summiya",
                last_name="Rasheed",
                email="SUMMIYA@Acme.COM",
            ),
        )

    with Session(migrated_engine) as session:
        challenge = session.scalars(select(OtpChallenge)).one()

    sent_otp = email_provider.sent[0]["otp"]
    assert challenge.email == "summiya@acme.com"
    assert challenge.purpose == "signup"
    assert challenge.user_id is None
    assert challenge.max_attempts == 5
    assert challenge.code_digest != sent_otp
    assert sent_otp not in challenge.code_digest
