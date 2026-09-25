from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from nexus.authorization import PermissionCheckError
from nexus.config.settings import load_settings
from nexus.infrastructure.persistence.authorization import SqlAlchemyPermissionChecker
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.infrastructure.persistence.models.permission import Permission
from nexus.infrastructure.persistence.models.role import Role
from nexus.infrastructure.persistence.models.role_permission import RolePermission
from nexus.infrastructure.persistence.models.user import User
from nexus.infrastructure.persistence.models.user_role import UserRole

BACKEND_ROOT = Path(__file__).resolve().parents[3]
UPLOAD_PERMISSION = "files.upload"


@dataclass(frozen=True)
class _PermissionFixture:
    organization_id: int
    organization_public_id: UUID
    other_organization_public_id: UUID
    user_id: int
    user_public_id: UUID
    unassigned_user_public_id: UUID
    role_id: int
    permission_id: int


def _normalize_postgresql_driver(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    database_url = _normalize_postgresql_driver(load_settings().database_url)
    database_name = f"nexus_permission_checker_test_{uuid.uuid4().hex}"
    test_url = make_url(database_url).set(database=database_name)
    admin_engine = create_engine(database_url, isolation_level="AUTOCOMMIT")

    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    except OperationalError:
        admin_engine.dispose()
        if os.environ.get("NEXUS_REQUIRE_POSTGRES_TESTS") == "true":
            raise
        pytest.skip("PostgreSQL is not available for permission checker tests")

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


@pytest.fixture
def permission_fixture(migrated_engine: Engine) -> _PermissionFixture:
    with Session(migrated_engine) as session:
        organization = Organization(name="Acme", slug="permission-acme")
        other_organization = Organization(name="Other", slug="permission-other")
        session.add_all([organization, other_organization])
        session.flush()

        user = User(
            organization_id=organization.id,
            email="allowed@example.com",
        )
        unassigned_user = User(
            organization_id=organization.id,
            email="unassigned@example.com",
        )
        role = Role(
            organization_id=organization.id,
            name="File uploader",
        )
        session.add_all([user, unassigned_user, role])
        session.flush()

        permission = session.scalar(
            select(Permission).where(Permission.key == UPLOAD_PERMISSION)
        )
        assert permission is not None
        session.add_all(
            [
                UserRole(
                    organization_id=organization.id,
                    user_id=user.id,
                    role_id=role.id,
                ),
                RolePermission(role_id=role.id, permission_id=permission.id),
            ]
        )
        session.commit()

        return _PermissionFixture(
            organization_id=organization.id,
            organization_public_id=organization.public_id,
            other_organization_public_id=other_organization.public_id,
            user_id=user.id,
            user_public_id=user.public_id,
            unassigned_user_public_id=unassigned_user.public_id,
            role_id=role.id,
            permission_id=permission.id,
        )


def _has_permission(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    organization_public_id: UUID,
    user_public_id: UUID,
    permission_key: str = UPLOAD_PERMISSION,
) -> bool:
    checker = SqlAlchemyPermissionChecker(session_factory)
    return asyncio.run(
        checker.has_permission(
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            permission_key=permission_key,
        )
    )


def test_assigned_permission_returns_true(
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
    permission_fixture: _PermissionFixture,
) -> None:
    assert _has_permission(
        authentication_async_session_factory,
        organization_public_id=permission_fixture.organization_public_id,
        user_public_id=permission_fixture.user_public_id,
    )


def test_missing_permission_or_assignment_returns_false(
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
    permission_fixture: _PermissionFixture,
) -> None:
    assert not _has_permission(
        authentication_async_session_factory,
        organization_public_id=permission_fixture.organization_public_id,
        user_public_id=permission_fixture.user_public_id,
        permission_key="files.delete",
    )
    assert not _has_permission(
        authentication_async_session_factory,
        organization_public_id=permission_fixture.organization_public_id,
        user_public_id=permission_fixture.unassigned_user_public_id,
    )


def test_cross_organization_identity_pair_returns_false(
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
    permission_fixture: _PermissionFixture,
) -> None:
    assert not _has_permission(
        authentication_async_session_factory,
        organization_public_id=permission_fixture.other_organization_public_id,
        user_public_id=permission_fixture.user_public_id,
    )


@pytest.mark.parametrize("missing_identity", ["organization", "user"])
def test_unknown_organization_or_user_returns_false(
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
    permission_fixture: _PermissionFixture,
    missing_identity: str,
) -> None:
    organization_public_id = permission_fixture.organization_public_id
    user_public_id = permission_fixture.user_public_id
    if missing_identity == "organization":
        organization_public_id = uuid.uuid4()
    else:
        user_public_id = uuid.uuid4()

    assert not _has_permission(
        authentication_async_session_factory,
        organization_public_id=organization_public_id,
        user_public_id=user_public_id,
    )


def test_inactive_or_deleted_records_disable_permission(
    migrated_engine: Engine,
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
    permission_fixture: _PermissionFixture,
) -> None:
    deleted_at = datetime(2026, 9, 25, tzinfo=UTC)
    changes: tuple[tuple[type[Organization | User | Role], int, str, object], ...] = (
        (Organization, permission_fixture.organization_id, "status", "inactive"),
        (Organization, permission_fixture.organization_id, "deleted_at", deleted_at),
        (User, permission_fixture.user_id, "status", "inactive"),
        (User, permission_fixture.user_id, "deleted_at", deleted_at),
        (Role, permission_fixture.role_id, "deleted_at", deleted_at),
    )

    for model_type, record_id, field_name, disabled_value in changes:
        with Session(migrated_engine) as session:
            model = session.get(model_type, record_id)
            assert model is not None
            enabled_value = getattr(model, field_name)
            setattr(model, field_name, disabled_value)
            session.commit()

        assert not _has_permission(
            authentication_async_session_factory,
            organization_public_id=permission_fixture.organization_public_id,
            user_public_id=permission_fixture.user_public_id,
        )

        with Session(migrated_engine) as session:
            model = session.get(model_type, record_id)
            assert model is not None
            setattr(model, field_name, enabled_value)
            session.commit()

        assert _has_permission(
            authentication_async_session_factory,
            organization_public_id=permission_fixture.organization_public_id,
            user_public_id=permission_fixture.user_public_id,
        )


def test_role_permission_revocation_is_observed_by_next_check(
    migrated_engine: Engine,
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
    permission_fixture: _PermissionFixture,
) -> None:
    assert _has_permission(
        authentication_async_session_factory,
        organization_public_id=permission_fixture.organization_public_id,
        user_public_id=permission_fixture.user_public_id,
    )

    with Session(migrated_engine) as session:
        assignment = session.get(
            RolePermission,
            (permission_fixture.role_id, permission_fixture.permission_id),
        )
        assert assignment is not None
        session.delete(assignment)
        session.commit()

    assert not _has_permission(
        authentication_async_session_factory,
        organization_public_id=permission_fixture.organization_public_id,
        user_public_id=permission_fixture.user_public_id,
    )


def test_sqlalchemy_failure_is_translated_safely(
    migrated_engine: Engine,
    authentication_async_session_factory: async_sessionmaker[AsyncSession],
    permission_fixture: _PermissionFixture,
) -> None:
    with migrated_engine.begin() as connection:
        connection.execute(text("DROP TABLE role_permissions"))

    checker = SqlAlchemyPermissionChecker(authentication_async_session_factory)
    with pytest.raises(PermissionCheckError) as exc_info:
        asyncio.run(
            checker.has_permission(
                organization_public_id=permission_fixture.organization_public_id,
                user_public_id=permission_fixture.user_public_id,
                permission_key=UPLOAD_PERMISSION,
            )
        )

    assert str(exc_info.value) == "Permission check failed"
    assert isinstance(exc_info.value.__cause__, SQLAlchemyError)
