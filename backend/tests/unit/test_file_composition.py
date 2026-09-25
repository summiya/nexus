from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.composition.files import build_file_composition
from nexus.config.settings import Settings
from nexus.files.ports import UploadGrant
from nexus.infrastructure.persistence.authorization import (
    SqlAlchemyPermissionChecker,
)
from nexus.infrastructure.persistence.file import SqlAlchemyFilePersistence


class StubUploadGrantIssuer:
    async def issue_upload_grant(
        self,
        *,
        storage_key: str,
        expires_at: datetime,
    ) -> UploadGrant:
        return UploadGrant(
            url=f"https://storage.example/{storage_key}?sig=value",
            method="PUT",
            headers={},
            expires_at=expires_at,
        )


def _settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/15",
        cors_allowed_origins=["https://nexus.example"],
        otp_hmac_secret="test-secret-value-with-enough-length",
        auth_token_secret="test-auth-token-secret-with-enough-length",
        refresh_token_secret="test-refresh-token-secret-with-enough-length",
        file_upload_max_size_bytes=123_456,
        file_upload_grant_ttl_seconds=900,
    )


def test_file_composition_builds_upload_service_from_shared_dependencies() -> None:
    session_factory = async_sessionmaker[AsyncSession]()
    issuer = StubUploadGrantIssuer()

    composition = build_file_composition(
        _settings(),
        session_factory=session_factory,
        upload_grant_issuer=issuer,
    )

    service = composition.initiate_upload
    assert service.intent_policy.max_size_bytes == 123_456
    assert isinstance(service.permission_checker, SqlAlchemyPermissionChecker)
    assert service.permission_checker._session_factory is session_factory
    assert isinstance(service.persistence, SqlAlchemyFilePersistence)
    assert service.persistence._session_factory is session_factory
    assert service.upload_grant_issuer is issuer
    assert service.grant_ttl == timedelta(seconds=900)
