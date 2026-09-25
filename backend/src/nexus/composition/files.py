"""File application composition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.config.settings import Settings
from nexus.files.application import InitiateFileUpload, UploadIntentPolicy
from nexus.files.ports import UploadGrantIssuer
from nexus.infrastructure.persistence.authorization import (
    SqlAlchemyPermissionChecker,
)
from nexus.infrastructure.upload_context import AesGcmUploadContextProtector


@dataclass(frozen=True)
class FileComposition:
    """Application-scoped File use cases."""

    initiate_upload: InitiateFileUpload


def build_file_composition(
    settings: Settings,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    upload_grant_issuer: UploadGrantIssuer,
) -> FileComposition:
    """Build File use cases from provider-neutral runtime dependencies."""

    return FileComposition(
        initiate_upload=InitiateFileUpload(
            intent_policy=UploadIntentPolicy(
                max_size_bytes=settings.file_upload_max_size_bytes
            ),
            permission_checker=SqlAlchemyPermissionChecker(session_factory),
            upload_grant_issuer=upload_grant_issuer,
            context_protector=AesGcmUploadContextProtector.from_base64url_key(
                settings.file_upload_context_key.get_secret_value()
            ),
            grant_ttl=timedelta(
                seconds=settings.file_upload_grant_ttl_seconds,
            ),
        )
    )


__all__ = ["FileComposition", "build_file_composition"]
