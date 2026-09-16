from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from nexus.errors import ErrorCode, NexusError
from nexus.infrastructure.persistence.models.auth_session import AuthSession
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.infrastructure.persistence.models.user import User
from nexus.security.authentication_tokens import AccessTokenService
from nexus.services.authentication_session import AuthenticationSessionService


class FakeAuthSessionRepository:
    def __init__(self, auth_session: AuthSession | None = None) -> None:
        self.auth_session = auth_session
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)
        if isinstance(value, AuthSession):
            value.id = 1
            value.public_id = uuid4()
            value.user = self.auth_session.user if self.auth_session else value.user

    def get_by_refresh_token_hash_for_update(
        self,
        refresh_token_hash: str,
    ) -> AuthSession | None:
        del refresh_token_hash
        return self.auth_session


def user() -> User:
    organization = Organization(
        id=7,
        public_id=uuid4(),
        name="Acme",
        slug="acme",
        status="active",
    )
    return User(
        id=11,
        public_id=uuid4(),
        organization_id=organization.id,
        organization=organization,
        email="person@example.com",
        status="active",
    )


def service(
    now: datetime | None = None,
    repository: FakeAuthSessionRepository | None = None,
) -> AuthenticationSessionService:
    return AuthenticationSessionService(
        access_token_service=AccessTokenService(
            secret="test-auth-token-secret-with-enough-length",
            expires_seconds=900,
            clock=lambda: now or datetime(2026, 9, 16, tzinfo=UTC),
        ),
        refresh_token_secret="test-refresh-token-secret-with-enough-length",
        refresh_token_expires_seconds=2_592_000,
        auth_session_repository=repository or FakeAuthSessionRepository(),
        clock=lambda: now or datetime(2026, 9, 16, tzinfo=UTC),
    )


def active_auth_session(account: User, *, refresh_hash: str) -> AuthSession:
    return AuthSession(
        id=1,
        public_id=uuid4(),
        user_id=account.id,
        user=account,
        refresh_token_hash=refresh_hash,
        expires_at=datetime(2026, 10, 16, tzinfo=UTC),
    )


def test_create_session_flushes_without_committing_and_hides_plaintext_refresh() -> (
    None
):
    repository = FakeAuthSessionRepository()
    account = user()

    result = service(repository=repository).create_session(user=account)

    assert result.token_type == "bearer"
    assert result.access_token
    assert result.refresh_token
    persisted = repository.added[0]
    assert isinstance(persisted, AuthSession)
    assert persisted.refresh_token_hash != result.refresh_token
    assert result.refresh_token not in persisted.refresh_token_hash


def test_refresh_session_rotates_token_and_updates_last_used_at() -> None:
    account = user()
    auth_service = service()
    old_refresh_token = "old-refresh-token"
    persisted = active_auth_session(
        account,
        refresh_hash=auth_service._hash_refresh_token(old_refresh_token),
    )
    repository = FakeAuthSessionRepository(auth_session=persisted)
    auth_service = service(repository=repository)

    result = auth_service.refresh_session(
        refresh_token=old_refresh_token,
    )

    assert result.refresh_token != old_refresh_token
    assert persisted.refresh_token_hash == auth_service._hash_refresh_token(
        result.refresh_token
    )
    assert persisted.last_used_at == datetime(2026, 9, 16, tzinfo=UTC)


def test_refresh_rejects_old_rotated_token() -> None:
    auth_service = service(repository=FakeAuthSessionRepository(auth_session=None))

    with pytest.raises(NexusError) as exc_info:
        auth_service.refresh_session(
            refresh_token="old-token",
        )

    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_expired_refresh_token_is_rejected() -> None:
    auth_service = service()
    account = user()
    token = "refresh-token"
    persisted = active_auth_session(
        account,
        refresh_hash=auth_service._hash_refresh_token(token),
    )
    persisted.expires_at = datetime(2026, 9, 15, tzinfo=UTC)

    with pytest.raises(NexusError) as exc_info:
        service(
            repository=FakeAuthSessionRepository(auth_session=persisted)
        ).refresh_session(refresh_token=token)

    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_revoked_refresh_token_is_rejected() -> None:
    auth_service = service()
    account = user()
    token = "refresh-token"
    persisted = active_auth_session(
        account,
        refresh_hash=auth_service._hash_refresh_token(token),
    )
    persisted.revoked_at = datetime(2026, 9, 16, tzinfo=UTC)

    with pytest.raises(NexusError) as exc_info:
        service(
            repository=FakeAuthSessionRepository(auth_session=persisted)
        ).refresh_session(refresh_token=token)

    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_revoke_session_sets_revoked_at_without_committing() -> None:
    account = user()
    auth_service = service()
    token = "refresh-token"
    persisted = active_auth_session(
        account,
        refresh_hash=auth_service._hash_refresh_token(token),
    )
    repository = FakeAuthSessionRepository(auth_session=persisted)
    auth_service = service(repository=repository)

    auth_service.revoke_session(refresh_token=token)

    assert persisted.revoked_at == datetime(2026, 9, 16, tzinfo=UTC)


def test_refresh_token_data_is_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    refresh_token = "refresh-token-value"
    auth_service = service()
    auth_service._hash_refresh_token(refresh_token)

    assert refresh_token not in caplog.text
    assert "test-refresh-token-secret-with-enough-length" not in caplog.text
