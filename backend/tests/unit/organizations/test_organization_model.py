from sqlalchemy import BigInteger

from nexus.domain.organizations import normalize_slug
from nexus.infrastructure.persistence.models import Organization


def test_normalize_slug_uses_canonical_representation() -> None:
    assert normalize_slug("  Acme Corporation  ") == "acme-corporation"


def test_organization_normalizes_slug() -> None:
    organization = Organization(name="Acme", slug="  Acme Corporation  ")

    assert organization.slug == "acme-corporation"


def test_organization_table_defines_internal_primary_key() -> None:
    organization_id = Organization.__table__.c.id

    assert isinstance(organization_id.type, BigInteger)
    assert organization_id.primary_key is True
    assert organization_id.autoincrement is True


def test_organization_table_defines_unique_public_id() -> None:
    public_id = Organization.__table__.c.public_id

    assert public_id.unique is True
    assert public_id.nullable is False
    assert public_id.index is True
    assert public_id.default is not None


def test_organization_table_defines_active_lifecycle_default() -> None:
    status = Organization.__table__.c.status

    assert status.default is not None
    assert status.default.arg == "active"


def test_organization_table_enforces_unique_slug() -> None:
    assert Organization.__table__.c.slug.unique is True


def test_organization_users_relationship_is_one_to_many() -> None:
    assert Organization.users.property.back_populates == "organization"
    assert Organization.users.property.uselist is True
