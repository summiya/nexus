import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError

from nexus.config.settings import settings
from nexus.infrastructure.persistence.models.otp_challenge import OtpChallenge

BACKEND_ROOT = Path(__file__).resolve().parents[3]


def normalize_postgresql_driver(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


@pytest.fixture
def migrated_database() -> Iterator[tuple[Config, Engine]]:
    database_url = normalize_postgresql_driver(settings.database_url)
    database_name = f"nexus_otp_challenge_test_{uuid.uuid4().hex}"
    test_url = make_url(database_url).set(database=database_name)
    admin_engine = create_engine(database_url, isolation_level="AUTOCOMMIT")

    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    except OperationalError:
        if os.environ.get("NEXUS_REQUIRE_POSTGRES_TESTS") == "true":
            raise
        pytest.skip("PostgreSQL is not available for migration tests")

    engine = create_engine(test_url)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["database_url"] = test_url.render_as_string(hide_password=False)

    try:
        yield config, engine
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


def test_otp_challenge_normalizes_email() -> None:
    challenge = OtpChallenge(
        email="  USER@Example.COM ",
        purpose="signup",
        code_digest="server-secret-bound-digest",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    assert challenge.email == "user@example.com"


def test_upgrade_creates_otp_challenge_schema(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, "head")

    inspector = inspect(engine)
    assert "otp_challenges" in inspector.get_table_names()

    columns = {column["name"]: column for column in inspector.get_columns("otp_challenges")}
    assert set(columns) == {
        "id",
        "user_id",
        "email",
        "purpose",
        "code_digest",
        "expires_at",
        "consumed_at",
        "attempt_count",
        "max_attempts",
        "locked_at",
        "created_at",
        "updated_at",
    }
    assert columns["user_id"]["nullable"] is True
    assert columns["email"]["nullable"] is False
    assert columns["code_digest"]["nullable"] is False
    assert columns["expires_at"]["nullable"] is False

    foreign_keys = inspector.get_foreign_keys("otp_challenges")
    assert len(foreign_keys) == 1
    assert foreign_keys[0]["referred_table"] == "users"
    assert foreign_keys[0]["options"] == {"ondelete": "CASCADE"}

    index_names = {index["name"] for index in inspector.get_indexes("otp_challenges")}
    assert "ix_otp_challenges_email_purpose" in index_names
    assert "ix_otp_challenges_user_id" in index_names

    constraint_names = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("otp_challenges")
    }
    assert {
        "ck_otp_challenges_purpose",
        "ck_otp_challenges_attempt_count_nonnegative",
        "ck_otp_challenges_max_attempts_positive",
        "ck_otp_challenges_attempt_count_within_limit",
    } <= constraint_names


def test_signup_challenge_allows_null_user_and_login_challenge_enforces_user_fk(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, "head")

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO otp_challenges (
                    id, user_id, email, purpose, code_digest, expires_at
                ) VALUES (
                    :id, NULL, :email, 'signup', :digest, now() + interval '5 minutes'
                )
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "email": "new-user@example.com",
                "digest": "server-secret-bound-digest",
            },
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO otp_challenges (
                    id, user_id, email, purpose, code_digest, expires_at
                ) VALUES (
                    :id, :user_id, :email, 'login', :digest, now() + interval '5 minutes'
                )
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "user_id": 999999,
                "email": "missing-user@example.com",
                "digest": "server-secret-bound-digest",
            },
        )


def test_database_rejects_invalid_purpose_and_attempt_counts(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, "head")

    invalid_values = [
        ("unknown", 0, 5),
        ("signup", -1, 5),
        ("login", 0, 0),
        ("login", 6, 5),
    ]

    for purpose, attempt_count, max_attempts in invalid_values:
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO otp_challenges (
                        id, email, purpose, code_digest, expires_at,
                        attempt_count, max_attempts
                    ) VALUES (
                        :id, :email, :purpose, :digest,
                        now() + interval '5 minutes', :attempt_count, :max_attempts
                    )
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "email": "constraint-test@example.com",
                    "purpose": purpose,
                    "digest": "server-secret-bound-digest",
                    "attempt_count": attempt_count,
                    "max_attempts": max_attempts,
                },
            )


def test_downgrade_removes_otp_challenges(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, "head")
    command.downgrade(config, "20260916_0003")

    assert "otp_challenges" not in inspect(engine).get_table_names()
