from nexus.domain.users import normalize_email
from nexus.infrastructure.persistence.models import User


def test_normalize_email_uses_canonical_representation() -> None:
    assert normalize_email("  Person@Example.COM  ") == "person@example.com"


def test_user_normalizes_email_and_defaults_to_active() -> None:
    user = User(email="  Person@Example.COM  ")

    assert user.email == "person@example.com"
    assert user.status == "active"
    assert user.email_verified_at is None


def test_user_table_enforces_unique_email() -> None:
    assert any(
        column.unique
        for column in User.__table__.columns
        if column.name == "email"
    )
