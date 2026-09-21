import os
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from nexus.authorization.bootstrap import (
    ADMINISTRATOR_ROLE_NAME,
    provision_administrator_role,
)
from nexus.config.settings import load_settings
from nexus.domain.permissions import PERMISSION_CATALOG
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.infrastructure.persistence.models.permission import Permission
from nexus.infrastructure.persistence.models.role import Role
from nexus.infrastructure.persistence.models.role_permission import RolePermission

BACKEND_ROOT = Path(__file__).resolve().parents[3]


def _normalize_postgresql_driver(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    database_url = _normalize_postgresql_driver(load_settings().database_url)
    database_name = f"nexus_admin_bootstrap_test_{uuid.uuid4().hex}"
    test_url = make_url(database_url).set(database=database_name)
    admin_engine = create_engine(database_url, isolation_level="AUTOCOMMIT")

    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    except OperationalError:
        admin_engine.dispose()
        if os.environ.get("NEXUS_REQUIRE_POSTGRES_TESTS") == "true":
            raise
        pytest.skip("PostgreSQL is not available for authorization integration tests")

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


def _create_organization(session: Session, slug: str) -> Organization:
    organization = Organization(name=f"Organization {slug}", slug=slug)
    session.add(organization)
    session.flush()
    return organization


def test_bootstrap_is_idempotent_and_attaches_complete_catalog(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session, session.begin():
        organization = _create_organization(session, "bootstrap-one")
        organization_id = organization.id
        first = provision_administrator_role(session, organization_id)
        second = provision_administrator_role(session, organization_id)
        role_id = first.id

        assert second.id == role_id

    with Session(migrated_engine) as session:
        roles = list(
            session.scalars(
                select(Role).where(
                    Role.organization_id == organization_id,
                    Role.name == ADMINISTRATOR_ROLE_NAME,
                )
            )
        )
        assert len(roles) == 1
        assert roles[0].is_system is True

        assigned_keys = set(
            session.scalars(
                select(Permission.key)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == role_id)
            )
        )
        assert assigned_keys == set(PERMISSION_CATALOG)


def test_bootstrap_creates_distinct_administrator_per_organization(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session, session.begin():
        first_org = _create_organization(session, "bootstrap-a")
        second_org = _create_organization(session, "bootstrap-b")
        first_role = provision_administrator_role(session, first_org.id)
        second_role = provision_administrator_role(session, second_org.id)

        assert first_role.id != second_role.id
        assert first_role.organization_id == first_org.id
        assert second_role.organization_id == second_org.id


def test_concurrent_bootstrap_produces_single_administrator_role(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session, session.begin():
        organization = _create_organization(session, "bootstrap-concurrent")
        organization_id = organization.id

    barrier = Barrier(2)

    def bootstrap() -> int:
        with Session(migrated_engine) as session, session.begin():
            barrier.wait()
            return provision_administrator_role(session, organization_id).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        role_ids = list(executor.map(lambda _: bootstrap(), range(2)))

    assert role_ids[0] == role_ids[1]

    with Session(migrated_engine) as session:
        role_count = session.scalar(
            select(func.count(Role.id)).where(
                Role.organization_id == organization_id,
                Role.name == ADMINISTRATOR_ROLE_NAME,
            )
        )
        mapping_count = session.scalar(
            select(func.count(RolePermission.permission_id)).where(
                RolePermission.role_id == role_ids[0]
            )
        )

        assert role_count == 1
        assert mapping_count == len(PERMISSION_CATALOG)


def test_bootstrap_failure_rolls_back_with_callers_transaction(
    migrated_engine: Engine,
) -> None:
    failed_slug = "bootstrap-rollback"

    with (
        pytest.raises(ValueError, match="Permission catalog is not seeded"),
        Session(migrated_engine) as session,
        session.begin(),
    ):
        organization = _create_organization(session, failed_slug)
        missing_permission = session.scalar(
            select(Permission).where(Permission.key == next(iter(PERMISSION_CATALOG)))
        )
        assert missing_permission is not None
        session.delete(missing_permission)
        session.flush()
        provision_administrator_role(session, organization.id)

    with Session(migrated_engine) as session:
        organization_count = session.scalar(
            select(func.count(Organization.id)).where(Organization.slug == failed_slug)
        )
        assert organization_count == 0
