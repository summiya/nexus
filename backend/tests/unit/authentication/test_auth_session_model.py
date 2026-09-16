from __future__ import annotations

from nexus.infrastructure.persistence.models.auth_session import AuthSession
from nexus.infrastructure.persistence.models.user import User


def test_auth_session_table_shape() -> None:
    columns = AuthSession.__table__.c

    assert set(columns.keys()) == {
        "id",
        "public_id",
        "user_id",
        "refresh_token_hash",
        "expires_at",
        "revoked_at",
        "last_used_at",
        "created_at",
        "updated_at",
    }
    assert columns.id.primary_key is True
    assert columns.public_id.unique is True
    assert columns.refresh_token_hash.unique is True
    assert columns.user_id.index is True
    assert columns.expires_at.index is True
    assert columns.revoked_at.index is True


def test_auth_session_user_relationship() -> None:
    assert AuthSession.user.property.back_populates == "auth_sessions"
    assert User.auth_sessions.property.back_populates == "user"
