from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from nexus.authentication.gateways import (
    AccessTokenClaims,
    AccessTokenGatewayError,
)
from nexus.authentication.repository import (
    AuthenticationIdentity,
    AuthenticationSession,
)
from nexus.authentication.session_service import (
    SessionPolicy,
    SessionService,
)
from nexus.errors import ErrorCode, NexusError


class FakeTransaction:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class FakeAuthenticationRepository:
    def __init__(
        self,
        session: AuthenticationSession | None = None,
        *,
        fail_update: bool = False,
    ) -> None:
        self.session = session
        self.fail_update = fail_update
        self.added: list[AuthenticationSession] = []

    async def add_session(self, session: AuthenticationSession) -> None:
        self.session = session
        self.added.append(session)

    async def get_session_by_refresh_token_hash_for_update(
        self,
        refresh_token_hash: str,
    ) -> AuthenticationSession | None:
        if (
            self.session is None
            or self.session.refresh_token_hash != refresh_token_hash
        ):
            return None
        return self.session

    async def update_session(self, session: AuthenticationSession) -> None:
        if self.fail_update:
            raise RuntimeError("session update failed")
        self.session = session


@dataclass(frozen=True)
class FakeAccessTokenGateway:
    expires_seconds: int = 900
    fail: bool = False

    def issue_access_token(self, claims: AccessTokenClaims) -> str:
        if self.fail:
            raise AccessTokenGatewayError("failed")
        return f"token:{claims.session_public_id}"


def identity() -> AuthenticationIdentity:
    return AuthenticationIdentity(
        user_public_id=uuid4(),
        organization_public_id=uuid4(),
    )


def service(
    *,
    now: datetime | None = None,
    repository: FakeAuthenticationRepository | None = None,
    transaction: FakeTransaction | None = None,
    token_gateway: FakeAccessTokenGateway | None = None,
) -> SessionService:
    return SessionService(
        policy=SessionPolicy(
            refresh_token_secret="test-refresh-token-secret-with-enough-length",
            refresh_token_expires_seconds=2_592_000,
        ),
        transaction=transaction or FakeTransaction(),
        repository=repository or FakeAuthenticationRepository(),  # type: ignore[arg-type]
        access_token_gateway=token_gateway or FakeAccessTokenGateway(),
        clock=lambda: now or datetime(2026, 9, 16, tzinfo=UTC),
    )


def active_session(
    auth_service: SessionService,
    *,
    refresh_token: str,
) -> AuthenticationSession:
    return AuthenticationSession(
        public_id=uuid4(),
        identity=identity(),
        refresh_token_hash=auth_service._hash_refresh_token(refresh_token),
        expires_at=datetime(2026, 10, 16, tzinfo=UTC),
    )


def test_create_session_commits_and_hides_plaintext_refresh_token() -> None:
    repository = FakeAuthenticationRepository()
    transaction = FakeTransaction()

    result = asyncio.run(
        service(
            repository=repository,
            transaction=transaction,
        ).create_session(identity=identity())
    )

    assert result.token_type == "bearer"
    assert result.access_token
    assert result.refresh_token
    assert repository.added[0].refresh_token_hash != result.refresh_token
    assert result.refresh_token not in repository.added[0].refresh_token_hash
    assert transaction.committed is True
    assert transaction.rolled_back is False


def test_stage_session_does_not_commit_or_roll_back() -> None:
    repository = FakeAuthenticationRepository()
    transaction = FakeTransaction()

    result = asyncio.run(
        service(
            repository=repository,
            transaction=transaction,
        ).stage_session(identity=identity())
    )

    assert result.access_token
    assert len(repository.added) == 1
    assert transaction.committed is False
    assert transaction.rolled_back is False


def test_stage_session_failure_does_not_commit_or_roll_back() -> None:
    transaction = FakeTransaction()

    with pytest.raises(NexusError) as exc_info:
        asyncio.run(
            service(
                transaction=transaction,
                token_gateway=FakeAccessTokenGateway(fail=True),
            ).stage_session(identity=identity())
        )

    assert exc_info.value.code == ErrorCode.SERVICE_UNAVAILABLE
    assert transaction.committed is False
    assert transaction.rolled_back is False


def test_refresh_session_rotates_token_and_commits_last_used_at() -> None:
    old_refresh_token = "old-refresh-token"
    initial_service = service()
    repository = FakeAuthenticationRepository(
        active_session(initial_service, refresh_token=old_refresh_token)
    )
    transaction = FakeTransaction()
    auth_service = service(repository=repository, transaction=transaction)

    result = asyncio.run(auth_service.refresh_session(refresh_token=old_refresh_token))

    assert result.refresh_token != old_refresh_token
    assert repository.session is not None
    assert repository.session.refresh_token_hash == auth_service._hash_refresh_token(
        result.refresh_token
    )
    assert repository.session.last_used_at == datetime(2026, 9, 16, tzinfo=UTC)
    assert transaction.committed is True


def test_refresh_rejects_old_rotated_token_and_rolls_back() -> None:
    transaction = FakeTransaction()
    auth_service = service(
        repository=FakeAuthenticationRepository(),
        transaction=transaction,
    )

    with pytest.raises(NexusError) as exc_info:
        asyncio.run(auth_service.refresh_session(refresh_token="old-token"))

    assert exc_info.value.code == ErrorCode.UNAUTHORIZED
    assert transaction.rolled_back is True


def test_refresh_persistence_failure_rolls_back_and_keeps_old_token_usable() -> None:
    old_refresh_token = "old-refresh-token"
    initial_service = service()
    persisted = active_session(initial_service, refresh_token=old_refresh_token)
    repository = FakeAuthenticationRepository(persisted, fail_update=True)
    transaction = FakeTransaction()
    auth_service = service(repository=repository, transaction=transaction)

    with pytest.raises(RuntimeError, match="session update failed"):
        asyncio.run(auth_service.refresh_session(refresh_token=old_refresh_token))

    assert repository.session == persisted
    assert transaction.committed is False
    assert transaction.rolled_back is True

    repository.fail_update = False
    result = asyncio.run(
        service(repository=repository).refresh_session(refresh_token=old_refresh_token)
    )
    assert result.refresh_token != old_refresh_token


@pytest.mark.parametrize("state", ["expired", "revoked"])
def test_inactive_refresh_token_is_rejected(state: str) -> None:
    token = "refresh-token"
    auth_service = service()
    persisted = active_session(auth_service, refresh_token=token)
    if state == "expired":
        persisted = AuthenticationSession(
            **{
                **persisted.__dict__,
                "expires_at": datetime(2026, 9, 15, tzinfo=UTC),
            }
        )
    else:
        persisted = AuthenticationSession(
            **{
                **persisted.__dict__,
                "revoked_at": datetime(2026, 9, 16, tzinfo=UTC),
            }
        )

    with pytest.raises(NexusError) as exc_info:
        asyncio.run(
            service(repository=FakeAuthenticationRepository(persisted)).refresh_session(
                refresh_token=token
            )
        )

    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_revoke_session_commits_revoked_at() -> None:
    token = "refresh-token"
    auth_service = service()
    repository = FakeAuthenticationRepository(
        active_session(auth_service, refresh_token=token)
    )
    transaction = FakeTransaction()
    auth_service = service(repository=repository, transaction=transaction)

    asyncio.run(auth_service.revoke_session(refresh_token=token))

    assert repository.session is not None
    assert repository.session.revoked_at == datetime(2026, 9, 16, tzinfo=UTC)
    assert transaction.committed is True


def test_access_token_failure_rolls_back_session() -> None:
    transaction = FakeTransaction()

    with pytest.raises(NexusError) as exc_info:
        asyncio.run(
            service(
                transaction=transaction,
                token_gateway=FakeAccessTokenGateway(fail=True),
            ).create_session(identity=identity())
        )

    assert exc_info.value.code == ErrorCode.SERVICE_UNAVAILABLE
    assert transaction.rolled_back is True


def test_refresh_token_data_is_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    refresh_token = "refresh-token-value"
    with pytest.raises(NexusError):
        asyncio.run(service().refresh_session(refresh_token=refresh_token))

    assert refresh_token not in caplog.text
    assert "test-refresh-token-secret-with-enough-length" not in caplog.text
