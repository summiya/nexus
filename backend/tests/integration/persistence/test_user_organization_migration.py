import json
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
    database_name = f"nexus_migration_test_{uuid.uuid4().hex}"
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


def upgrade(config: Config) -> None:
    command.upgrade(config, "head")


def downgrade(config: Config) -> None:
    command.downgrade(config, "base")


def insert_organization(connection: sa.Connection, slug: str) -> int:
    return connection.execute(
        text(
            """
            INSERT INTO organizations (
                public_id, name, slug, status, settings_json
            )
            VALUES (
                :public_id, :name, :slug, 'active', CAST(:settings_json AS JSONB)
            )
            RETURNING id
            """
        ),
        {
            "public_id": str(uuid.uuid4()),
            "name": f"Organization {slug}",
            "slug": slug,
            "settings_json": json.dumps({}),
        },
    ).scalar_one()


def insert_user(connection: sa.Connection, organization_id: int, email: str) -> int:
    return connection.execute(
        text(
            """
            INSERT INTO users (
                public_id, organization_id, email, status
            )
            VALUES (
                :public_id, :organization_id, :email, 'active'
            )
            RETURNING id
            """
        ),
        {
            "public_id": str(uuid.uuid4()),
            "organization_id": organization_id,
            "email": email,
        },
    ).scalar_one()


def test_upgrade_creates_organizations_and_users_schema(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database

    upgrade(config)

    inspector = inspect(engine)
    assert {"organizations", "users"}.issubset(set(inspector.get_table_names()))

    organization_columns = {
        column["name"]: column for column in inspector.get_columns("organizations")
    }
    user_columns = {column["name"]: column for column in inspector.get_columns("users")}

    assert inspector.get_pk_constraint("organizations")["constrained_columns"] == ["id"]
    assert organization_columns["public_id"]["nullable"] is False
    assert organization_columns["slug"]["nullable"] is False
    assert organization_columns["settings_json"]["nullable"] is False
    assert organization_columns["created_at"]["nullable"] is False
    assert organization_columns["updated_at"]["nullable"] is False

    assert inspector.get_pk_constraint("users")["constrained_columns"] == ["id"]
    assert user_columns["public_id"]["nullable"] is False
    assert user_columns["organization_id"]["nullable"] is False
    assert user_columns["email"]["nullable"] is False
    assert user_columns["created_at"]["nullable"] is False
    assert user_columns["updated_at"]["nullable"] is False

    foreign_key = inspector.get_foreign_keys("users")[0]
    assert foreign_key["name"] == "fk_users_organization_id_organizations"
    assert foreign_key["constrained_columns"] == ["organization_id"]
    assert foreign_key["referred_table"] == "organizations"
    assert foreign_key["referred_columns"] == ["id"]
    assert foreign_key["options"] == {"ondelete": "CASCADE"}


def test_postgresql_constraints_enforce_user_organization_contract(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    upgrade(config)

    with engine.begin() as connection:
        organization_id = insert_organization(connection, "acme")
        first_user_id = insert_user(connection, organization_id, "one@example.com")
        second_user_id = insert_user(connection, organization_id, "two@example.com")

    assert first_user_id != second_user_id

    with pytest.raises(IntegrityError), engine.begin() as connection:
        insert_organization(connection, "acme")

    with pytest.raises(IntegrityError), engine.begin() as connection:
        insert_user(connection, organization_id, "one@example.com")

    with pytest.raises(IntegrityError), engine.begin() as connection:
        insert_user(connection, organization_id + 999, "missing-org@example.com")

    inspector = inspect(engine)
    assert "organization_memberships" not in inspector.get_table_names()
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    assert "organization_id" in user_columns
    assert "role_id" not in user_columns
    assert "is_admin" not in user_columns
    assert "is_owner" not in user_columns


def test_downgrade_removes_user_and_organization_tables(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database

    upgrade(config)
    downgrade(config)

    tables = set(inspect(engine).get_table_names())
    assert "users" not in tables
    assert "organizations" not in tables


def test_upgrade_downgrade_upgrade_is_reversible(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database

    upgrade(config)
    downgrade(config)
    upgrade(config)

    tables = set(inspect(engine).get_table_names())
    assert {"organizations", "users"}.issubset(tables)
