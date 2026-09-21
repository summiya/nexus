import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError

from nexus.config.settings import load_settings

BACKEND_ROOT = Path(__file__).resolve().parents[3]


def normalize_postgresql_driver(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


@pytest.fixture
def migrated_database() -> Iterator[tuple[Config, Engine]]:
    database_url = normalize_postgresql_driver(load_settings().database_url)
    database_name = f"nexus_auth_session_migration_test_{uuid.uuid4().hex}"
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


def insert_organization(connection: sa.Connection) -> int:
    return connection.execute(
        text(
            """
            INSERT INTO organizations (
                public_id, name, slug, status, settings_json
            )
            VALUES (
                :public_id, 'Acme', 'acme', 'active', CAST('{}' AS JSONB)
            )
            RETURNING id
            """
        ),
        {"public_id": str(uuid.uuid4())},
    ).scalar_one()


def insert_user(connection: sa.Connection, organization_id: int) -> int:
    return connection.execute(
        text(
            """
            INSERT INTO users (
                public_id, organization_id, email, status
            )
            VALUES (
                :public_id, :organization_id, 'person@example.com', 'active'
            )
            RETURNING id
            """
        ),
        {"public_id": str(uuid.uuid4()), "organization_id": organization_id},
    ).scalar_one()


def test_upgrade_creates_auth_sessions_schema(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, "head")

    inspector = inspect(engine)
    assert "auth_sessions" in inspector.get_table_names()

    columns = {
        column["name"]: column for column in inspector.get_columns("auth_sessions")
    }
    assert set(columns) == {
        "id",
        "public_id",
        "user_id",
        "refresh_token_hash",
        "expires_at",
        "revoked_at",
        "last_used_at",
        "created_at",
        "updated_at",
    }
    assert columns["user_id"]["nullable"] is False
    assert columns["refresh_token_hash"]["nullable"] is False
    assert columns["expires_at"]["nullable"] is False

    index_names = {index["name"] for index in inspector.get_indexes("auth_sessions")}
    assert {
        "ix_auth_sessions_public_id",
        "ix_auth_sessions_user_id",
        "ix_auth_sessions_refresh_token_hash",
        "ix_auth_sessions_expires_at",
        "ix_auth_sessions_revoked_at",
    } <= index_names

    foreign_key = inspector.get_foreign_keys("auth_sessions")[0]
    assert foreign_key["name"] == "fk_auth_sessions_user_id_users"
    assert foreign_key["referred_table"] == "users"
    assert foreign_key["options"] == {"ondelete": "CASCADE"}


def test_auth_session_constraints(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, "head")

    with engine.begin() as connection:
        organization_id = insert_organization(connection)
        user_id = insert_user(connection, organization_id)
        connection.execute(
            text(
                """
                INSERT INTO auth_sessions (
                    public_id, user_id, refresh_token_hash, expires_at
                )
                VALUES (
                    :public_id, :user_id, 'refresh-hash', now() + interval '30 days'
                )
                """
            ),
            {"public_id": str(uuid.uuid4()), "user_id": user_id},
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO auth_sessions (
                    public_id, user_id, refresh_token_hash, expires_at
                )
                VALUES (
                    :public_id, :user_id, 'refresh-hash', now() + interval '30 days'
                )
                """
            ),
            {"public_id": str(uuid.uuid4()), "user_id": user_id},
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO auth_sessions (
                    public_id, user_id, refresh_token_hash, expires_at
                )
                VALUES (
                    :public_id, 999999, 'other-hash', now() + interval '30 days'
                )
                """
            ),
            {"public_id": str(uuid.uuid4())},
        )


def test_downgrade_removes_auth_sessions(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, "head")
    command.downgrade(config, "20260916_0004")

    assert "auth_sessions" not in inspect(engine).get_table_names()
