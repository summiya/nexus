from unittest.mock import MagicMock

import pytest

from nexus.authorization.bootstrap import (
    ADMINISTRATOR_ROLE_NAME,
    provision_administrator_role,
)
from nexus.domain.permissions import PERMISSION_CATALOG
from nexus.infrastructure.persistence.models.permission import Permission
from nexus.infrastructure.persistence.models.role import Role


def _permission(permission_id: int, key: str) -> Permission:
    permission = Permission(key=key, description=PERMISSION_CATALOG[key])
    permission.id = permission_id
    return permission


def test_provision_administrator_role_creates_system_role_with_all_permissions() -> None:
    session = MagicMock()
    permissions = [
        _permission(index, key) for index, key in enumerate(PERMISSION_CATALOG, start=1)
    ]
    session.scalar.side_effect = [7, None]
    session.scalars.side_effect = [permissions, []]

    def assign_role_id() -> None:
        added_role = next(
            call.args[0]
            for call in session.add.call_args_list
            if isinstance(call.args[0], Role)
        )
        added_role.id = 42

    session.flush.side_effect = [assign_role_id, None]

    role = provision_administrator_role(session, organization_id=7)

    assert role.organization_id == 7
    assert role.name == ADMINISTRATOR_ROLE_NAME
    assert role.is_system is True
    role_permission_adds = [
        call.args[0]
        for call in session.add.call_args_list
        if not isinstance(call.args[0], Role)
    ]
    assert {mapping.permission_id for mapping in role_permission_adds} == {
        permission.id for permission in permissions
    }
    session.commit.assert_not_called()


def test_provision_administrator_role_is_idempotent() -> None:
    session = MagicMock()
    role = Role(organization_id=7, name=ADMINISTRATOR_ROLE_NAME, is_system=True)
    role.id = 42
    permissions = [
        _permission(index, key) for index, key in enumerate(PERMISSION_CATALOG, start=1)
    ]
    session.scalar.side_effect = [7, role]
    session.scalars.side_effect = [permissions, [permission.id for permission in permissions]]

    returned = provision_administrator_role(session, organization_id=7)

    assert returned is role
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_provision_administrator_role_rejects_missing_organization() -> None:
    session = MagicMock()
    session.scalar.return_value = None

    with pytest.raises(ValueError, match="does not exist"):
        provision_administrator_role(session, organization_id=999)

    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_provision_administrator_role_fails_when_catalog_is_not_seeded() -> None:
    session = MagicMock()
    session.scalar.side_effect = [7, None]
    session.scalars.side_effect = [[], []]

    def assign_role_id() -> None:
        added_role = session.add.call_args.args[0]
        added_role.id = 42

    session.flush.side_effect = assign_role_id

    with pytest.raises(ValueError, match="Permission catalog is not seeded"):
        provision_administrator_role(session, organization_id=7)

    session.commit.assert_not_called()


def test_provision_administrator_role_rejects_non_system_name_collision() -> None:
    session = MagicMock()
    role = Role(organization_id=7, name=ADMINISTRATOR_ROLE_NAME, is_system=False)
    role.id = 42
    session.scalar.side_effect = [7, role]

    with pytest.raises(ValueError, match="not a system role"):
        provision_administrator_role(session, organization_id=7)

    session.commit.assert_not_called()
