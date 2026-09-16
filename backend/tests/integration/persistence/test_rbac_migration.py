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
from nexus.domain.permissions import PERMISSION_CATALOG

BACKEND_ROOT = Path(__file__).resolve().parents[3]


def normalize_postgresql_driver(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


@pytest.fixture
def migrated_database() -> Iterator[tuple[Config, Engine]]:
    database_url = normalize_postgresql_driver(settings.database_url)
    database_name = f"nexus_rbac_migration_test_{uuid.uuid4().hex}"
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


def test_upgrade_creates_rbac_schema_and_seeds_permissions(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    upgrade(config)

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {
        "organizations",
        "users",
        "roles",
        "permissions",
        "role_permissions",
    }.issubset(tables)

    role_columns = {column["name"]: column for column in inspector.get_columns("roles")}
    permission_columns = {
        column["name"]: column for column in inspector.get_columns("permissions")
    }
    assert role_columns["organization_id"]["nullable"] is False
    assert role_columns["name"]["nullable"] is False
    assert role_columns["is_system"]["nullable"] is False
    assert permission_columns["key"]["nullable"] is False
    assert inspector.get_pk_constraint("role_permissions")["constrained_columns"] == [
        "role_id",
        "permission_id",
    ]

    with engine.connect() as connection:
        keys = set(connection.execute(text("SELECT key FROM permissions")).scalars())
    assert keys == set(PERMISSION_CATALOG)


def test_postgresql_enforces_rbac_constraints(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    upgrade(config)

    with engine.begin() as connection:
        organization_one = insert_organization(connection, "rbac-one")
        organization_two = insert_organization(connection, "rbac-two")
        role_one = insert_role(connection, organization_one, "Administrator")
        role_two = insert_role(connection, organization_two, "Administrator")
        permission_id = connection.execute(
            text("SELECT id FROM permissions WHERE key = 'roles.read'")
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "VALUES (:role_id, :permission_id)"
            ),
            {"role_id": role_one, "permission_id": permission_id},
        )

    assert role_one != role_two

    with pytest.raises(IntegrityError), engine.begin() as connection:
        insert_role(connection, organization_one, "Administrator")

    with pytest.raises(IntegrityError), engine.begin() as connection:
        insert_role(connection, organization_one + 99999, "Missing Organization")

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO permissions (public_id, key, description) "
                "VALUES (:public_id, 'roles.read', 'Duplicate')"
            ),
            {"public_id": str(uuid.uuid4())},
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "VALUES (:role_id, :permission_id)"
            ),
            {"role_id": role_one, "permission_id": permission_id},
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "VALUES (:role_id, :permission_id)"
            ),
            {"role_id": role_one + 99999, "permission_id": permission_id},
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "VALUES (:role_id, :permission_id)"
            ),
            {"role_id": role_one, "permission_id": permission_id + 99999},
        )


def test_rbac_revision_downgrade_preserves_identity_tables(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    upgrade(config)

    command.downgrade(config, "20260916_0001")

    tables = set(inspect(engine).get_table_names())
    assert {"organizations", "users"}.issubset(tables)
    assert "roles" not in tables
    assert "permissions" not in tables
    assert "role_permissions" not in tables


def test_rbac_upgrade_downgrade_upgrade_is_reversible(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database

    upgrade(config)
    command.downgrade(config, "20260916_0001")
    upgrade(config)

    tables = set(inspect(engine).get_table_names())
    assert {"roles", "permissions", "role_permissions"}.issubset(tables)
    with engine.connect() as connection:
        keys = set(connection.execute(text("SELECT key FROM permissions")).scalars())
    assert keys == set(PERMISSION_CATALOG)
