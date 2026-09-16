from nexus.domain.organizations import normalize_slug
from nexus.infrastructure.persistence.models import Organization


def test_normalize_slug_uses_canonical_representation() -> None:
    assert normalize_slug("  Acme Corporation  ") == "acme-corporation"


def test_organization_normalizes_slug_and_defaults_to_active() -> None:
    organization = Organization(name="Acme", slug="  Acme Corporation  ")

    assert organization.slug == "acme-corporation"
    assert organization.status == "active"


def test_organization_table_enforces_unique_slug() -> None:
    assert any(
        column.unique
        for column in Organization.__table__.columns
        if column.name == "slug"
    )
