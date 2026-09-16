from sqlalchemy import BigInteger, CheckConstraint

from nexus.infrastructure.persistence.models import (
    Organization,
    OrganizationMembership,
    User,
)


def test_membership_table_defines_internal_and_public_ids() -> None:
    membership_id = OrganizationMembership.__table__.c.id
    public_id = OrganizationMembership.__table__.c.public_id

    assert isinstance(membership_id.type, BigInteger)
    assert membership_id.primary_key is True
    assert membership_id.autoincrement is True
    assert public_id.unique is True
    assert public_id.nullable is False
    assert public_id.index is True
    assert public_id.default is not None


def test_membership_foreign_keys_follow_internal_id_convention() -> None:
    organization_fk = next(iter(OrganizationMembership.__table__.c.organization_id.foreign_keys))
    user_fk = next(iter(OrganizationMembership.__table__.c.user_id.foreign_keys))
    inviter_fk = next(iter(OrganizationMembership.__table__.c.invited_by.foreign_keys))

    assert organization_fk.target_fullname == "organizations.id"
    assert user_fk.target_fullname == "users.id"
    assert inviter_fk.target_fullname == "users.id"
    assert organization_fk.ondelete == "CASCADE"
    assert user_fk.ondelete == "CASCADE"
    assert inviter_fk.ondelete == "SET NULL"


def test_membership_enforces_v1_single_organization_per_user() -> None:
    user_id = OrganizationMembership.__table__.c.user_id

    assert user_id.unique is True
    assert user_id.nullable is False
    assert user_id.index is True


def test_membership_indexes_organization_and_inviter() -> None:
    assert OrganizationMembership.__table__.c.organization_id.index is True
    assert OrganizationMembership.__table__.c.invited_by.index is True


def test_membership_status_excludes_invited_state() -> None:
    constraints = [
        constraint
        for constraint in OrganizationMembership.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    ]

    status_constraint = next(
        constraint
        for constraint in constraints
        if constraint.name == "ck_organization_memberships_status"
    )
    expression = str(status_constraint.sqltext)

    assert "active" in expression
    assert "deactivated" in expression
    assert "removed" in expression
    assert "invited" not in expression


def test_membership_has_no_role_dependency() -> None:
    assert "role_id" not in OrganizationMembership.__table__.c


def test_membership_lifecycle_defaults_to_active() -> None:
    status = OrganizationMembership.__table__.c.status

    assert status.default is not None
    assert status.default.arg == "active"
    assert OrganizationMembership.__table__.c.joined_at.nullable is True
    assert OrganizationMembership.__table__.c.deleted_at.nullable is True


def test_membership_relationships_are_bidirectional() -> None:
    assert OrganizationMembership.organization.property.back_populates == "memberships"
    assert OrganizationMembership.user.property.back_populates == "organization_membership"
    assert OrganizationMembership.inviter.property.back_populates == (
        "invited_organization_memberships"
    )
    assert Organization.memberships.property.back_populates == "organization"
    assert User.organization_membership.property.uselist is False
