from nexus.domain.organizations import normalize_slug
from nexus.infrastructure.persistence.models import Organization


def test_normalize_slug_uses_canonical_representation() -> None:
    assert normalize_slug("  Acme Corporation  ") == "acme-corporation"


def test_organization_normalizes_slug() -> None:
    organization = Organization(name="Acme", slug="  Acme Corporation  ")

    assert organization.slug == "acme-corporation"


def test_organization_table_defines_active_lifecycle_default() -> None:
    status = Organization.__table__.c.status

    assert status.default is not None
    assert status.default.arg == "active"


def test_organization_table_enforces_unique_slug() -> None:
    assert Organization.__table__.c.slug.unique is True
