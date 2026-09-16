from sqlalchemy import BigInteger

from nexus.domain.users import normalize_email
from nexus.infrastructure.persistence.models import User


def test_normalize_email_uses_canonical_representation() -> None:
    assert normalize_email("  Person@Example.COM  ") == "person@example.com"


def test_user_normalizes_email() -> None:
    user = User(email="  Person@Example.COM  ")

    assert user.email == "person@example.com"
    assert user.email_verified_at is None


def test_user_table_defines_internal_primary_key() -> None:
    user_id = User.__table__.c.id

    assert isinstance(user_id.type, BigInteger)
    assert user_id.primary_key is True
    assert user_id.autoincrement is True


def test_user_table_defines_unique_public_id() -> None:
    public_id = User.__table__.c.public_id

    assert public_id.unique is True
    assert public_id.nullable is False
    assert public_id.index is True
    assert public_id.default is not None


def test_user_table_defines_active_lifecycle_default() -> None:
    status = User.__table__.c.status

    assert status.default is not None
    assert status.default.arg == "active"


def test_user_table_enforces_unique_email() -> None:
    assert User.__table__.c.email.unique is True
