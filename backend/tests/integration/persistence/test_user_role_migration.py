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

from nexus.config.settings import settings

BACKEND_ROOT = Path(__file__).resolve().parents[3]


def normalize_postgresql_driver(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


@pytest.fixture
def migrated_database() -> Iterator[tuple[Config, Engine]]:
    database_url = normalize_postgresql_driver(settings.database_url)
    database_name = f"nexus_user_role_migration_test_{uuid.uuid4().hex}"
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
            INSERT INTO users (public_id, organization_id, email, status)
            VALUES (:public_id, :organization_id, :email, 'active')
            RETURNING id
            """
        ),
        {
            "public_id": str(uuid.uuid4()),
            "organization_id": organization_id,
            "email": email,
        },
    ).scalar_one()


def insert_role(connection: sa.Connection, organization_id: int, name: str) -> int:
    return connection.execute(
        text(
            """
            INSERT INTO roles (public_id, organization_id, name, is_system)
            VALUES (:public_id, :organization_id, :name, false)
            RETURNING id
            """
        ),
        {
            "public_id": str(uuid.uuid4()),
            "organization_id": organization_id,
            "name": name,
        },
    ).scalar_one()


def insert_user_role(
    connection: sa.Connection, organization_id: int, user_id: int, role_id: int
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO user_roles (organization_id, user_id, role_id)
            VALUES (:organization_id, :user_id, :role_id)
            """
        ),
        {
            "organization_id": organization_id,
            "user_id": user_id,
            "role_id": role_id,
        },
    )


def test_upgrade_creates_tenant_safe_user_roles_schema(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    upgrade(config)

    inspector = inspect(engine)
    assert "user_roles" in inspector.get_table_names()
    assert inspector.get_pk_constraint("user_roles")["constrained_columns"] == [
        "user_id",
        "role_id",
    ]

    columns = {column["name"]: column for column in inspector.get_columns("user_roles")}
    assert columns["organization_id"]["nullable"] is False
    assert columns["user_id"]["nullable"] is False
    assert columns["role_id"]["nullable"] is False
    assert columns["created_at"]["nullable"] is False

    foreign_keys = {
        foreign_key["name"]: foreign_key
        for foreign_key in inspector.get_foreign_keys("user_roles")
    }
    user_fk = foreign_keys["fk_user_roles_user_organization_users"]
    role_fk = foreign_keys["fk_user_roles_role_organization_roles"]

    assert user_fk["constrained_columns"] == ["user_id", "organization_id"]
    assert user_fk["referred_table"] == "users"
    assert user_fk["referred_columns"] == ["id", "organization_id"]
    assert user_fk["options"] == {"ondelete": "CASCADE"}

    assert role_fk["constrained_columns"] == ["role_id", "organization_id"]
    assert role_fk["referred_table"] == "roles"
    assert role_fk["referred_columns"] == ["id", "organization_id"]
    assert role_fk["options"] == {"ondelete": "CASCADE"}


def test_postgresql_enforces_user_role_and_tenant_constraints(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    upgrade(config)

    with engine.begin() as connection:
        organization_one = insert_organization(connection, "user-role-one")
        organization_two = insert_organization(connection, "user-role-two")
        user_id = insert_user(connection, organization_one, "user-role@example.com")
        role_one = insert_role(connection, organization_one, "Administrator")
        role_two = insert_role(connection, organization_two, "Administrator")
        insert_user_role(connection, organization_one, user_id, role_one)

    with pytest.raises(IntegrityError), engine.begin() as connection:
        insert_user_role(connection, organization_one, user_id, role_one)

    with pytest.raises(IntegrityError), engine.begin() as connection:
        insert_user_role(connection, organization_one, user_id + 99999, role_one)

    with pytest.raises(IntegrityError), engine.begin() as connection:
        insert_user_role(connection, organization_one, user_id, role_one + 99999)

    with pytest.raises(IntegrityError), engine.begin() as connection:
        insert_user_role(connection, organization_one, user_id, role_two)

    with pytest.raises(IntegrityError), engine.begin() as connection:
        insert_user_role(connection, organization_two, user_id, role_two)


def test_user_role_foreign_keys_cascade_from_user_and_role(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    upgrade(config)

    with engine.begin() as connection:
        organization_id = insert_organization(connection, "cascade")
        user_one = insert_user(connection, organization_id, "cascade-one@example.com")
        user_two = insert_user(connection, organization_id, "cascade-two@example.com")
        role_one = insert_role(connection, organization_id, "Operator")
        role_two = insert_role(connection, organization_id, "Reviewer")
        insert_user_role(connection, organization_id, user_one, role_one)
        insert_user_role(connection, organization_id, user_two, role_two)

        connection.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_one})
        user_assignment = connection.execute(
            text("SELECT count(*) FROM user_roles WHERE user_id = :user_id"),
            {"user_id": user_one},
        ).scalar_one()

        connection.execute(text("DELETE FROM roles WHERE id = :role_id"), {"role_id": role_two})
        role_assignment = connection.execute(
            text("SELECT count(*) FROM user_roles WHERE role_id = :role_id"),
            {"role_id": role_two},
        ).scalar_one()

    assert user_assignment == 0
    assert role_assignment == 0


def test_user_role_revision_downgrade_preserves_prior_rbac_schema(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    upgrade(config)

    command.downgrade(config, "20260916_0002")

    tables = set(inspect(engine).get_table_names())
    assert "user_roles" not in tables
    assert {"users", "roles", "permissions", "role_permissions"}.issubset(tables)
