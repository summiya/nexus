from sqlalchemy import BigInteger, UniqueConstraint

from nexus.domain.permissions import PERMISSION_CATALOG
from nexus.infrastructure.persistence.models import (
    Organization,
    Permission,
    Role,
    RolePermission,
)


def test_role_uses_project_identity_and_organization_fk() -> None:
    role_id = Role.__table__.c.id
    public_id = Role.__table__.c.public_id
    organization_id = Role.__table__.c.organization_id
    organization_fk = next(iter(organization_id.foreign_keys))

    assert isinstance(role_id.type, BigInteger)
    assert role_id.primary_key is True
    assert role_id.autoincrement is True
    assert public_id.nullable is False
    assert public_id.unique is True
    assert public_id.index is True
    assert public_id.default is not None
    assert organization_id.nullable is False
    assert organization_id.index is True
    assert organization_fk.target_fullname == "organizations.id"
    assert organization_fk.ondelete == "CASCADE"


def test_role_name_is_unique_within_organization() -> None:
    unique_constraints = {
        tuple(constraint.columns.keys())
        for constraint in Role.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("organization_id", "name") in unique_constraints


def test_role_defines_system_flag_and_lifecycle_fields() -> None:
    is_system = Role.__table__.c.is_system

    assert is_system.nullable is False
    assert is_system.default is not None
    assert is_system.default.arg is False
    assert Role.__table__.c.created_at.nullable is False
    assert Role.__table__.c.updated_at.nullable is False
    assert Role.__table__.c.deleted_at.nullable is True


def test_permission_defines_unique_stable_key() -> None:
    permission_id = Permission.__table__.c.id
    public_id = Permission.__table__.c.public_id
    key = Permission.__table__.c.key

    assert isinstance(permission_id.type, BigInteger)
    assert permission_id.primary_key is True
    assert permission_id.autoincrement is True
    assert public_id.nullable is False
    assert public_id.unique is True
    assert public_id.index is True
    assert key.nullable is False
    assert key.unique is True
    assert key.index is True


def test_role_permission_uses_composite_primary_key_and_foreign_keys() -> None:
    role_id = RolePermission.__table__.c.role_id
    permission_id = RolePermission.__table__.c.permission_id
    role_fk = next(iter(role_id.foreign_keys))
    permission_fk = next(iter(permission_id.foreign_keys))

    assert role_id.primary_key is True
    assert permission_id.primary_key is True
    assert role_fk.target_fullname == "roles.id"
    assert role_fk.ondelete == "CASCADE"
    assert permission_fk.target_fullname == "permissions.id"
    assert permission_fk.ondelete == "CASCADE"


def test_rbac_relationships_are_bidirectional() -> None:
    assert Organization.roles.property.back_populates == "organization"
    assert Role.organization.property.back_populates == "roles"
    assert Role.role_permissions.property.back_populates == "role"
    assert RolePermission.role.property.back_populates == "role_permissions"
    assert Permission.role_permissions.property.back_populates == "permission"
    assert RolePermission.permission.property.back_populates == "role_permissions"
    assert Role.permissions.property.secondary is RolePermission.__table__
    assert Permission.roles.property.secondary is RolePermission.__table__


def test_initial_permission_catalog_contains_only_current_auth_keys() -> None:
    assert set(PERMISSION_CATALOG) == {
        "users.read",
        "users.manage",
        "organizations.read",
        "organizations.manage",
        "roles.read",
        "roles.manage",
        "permissions.read",
    }
    assert len(PERMISSION_CATALOG) == len(set(PERMISSION_CATALOG))
    assert all(description for description in PERMISSION_CATALOG.values())
