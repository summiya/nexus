"""Fernet-encrypted credential storage for explicit local/test use."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import UUID, uuid4

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from nexus.model_providers.domain import (
    CredentialReference,
    OrganizationProviderId,
    ProviderCredentialSecret,
)
from nexus.model_providers.ports import (
    CredentialNotFoundError,
    CredentialStoreError,
    credential_storage_name,
)


class LocalEncryptedCredentialStore:
    """Store one encrypted file per credential without environment policy."""

    def __init__(self, *, path: Path, encryption_key: SecretStr) -> None:
        self._path = path
        try:
            self._fernet = Fernet(encryption_key.get_secret_value().encode("ascii"))
        except (ValueError, TypeError, UnicodeEncodeError):
            raise ValueError("Local credential encryption key is invalid.") from None
        self._lock = asyncio.Lock()

    def _credential_path(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        credential_reference: CredentialReference,
    ) -> Path:
        return self._path / credential_storage_name(
            organization_public_id=organization_public_id,
            provider_id=provider_id,
            credential_reference=credential_reference,
        )

    async def put(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        credential_reference: CredentialReference,
        secret: ProviderCredentialSecret,
    ) -> None:
        target = self._credential_path(
            organization_public_id=organization_public_id,
            provider_id=provider_id,
            credential_reference=credential_reference,
        )
        ciphertext = self._fernet.encrypt(secret.reveal().encode("utf-8"))
        async with self._lock:
            try:
                await asyncio.to_thread(self._atomic_write, target, ciphertext)
            except OSError:
                raise CredentialStoreError("Credential could not be stored.") from None

    async def resolve(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        credential_reference: CredentialReference,
    ) -> ProviderCredentialSecret:
        target = self._credential_path(
            organization_public_id=organization_public_id,
            provider_id=provider_id,
            credential_reference=credential_reference,
        )
        async with self._lock:
            try:
                ciphertext = await asyncio.to_thread(target.read_bytes)
            except FileNotFoundError:
                raise CredentialNotFoundError("Credential was not found.") from None
            except OSError:
                raise CredentialStoreError(
                    "Credential could not be resolved."
                ) from None
        try:
            plaintext = self._fernet.decrypt(ciphertext).decode("utf-8")
            return ProviderCredentialSecret(plaintext)
        except (InvalidToken, UnicodeDecodeError, ValueError):
            raise CredentialStoreError("Credential could not be resolved.") from None

    async def delete(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        credential_reference: CredentialReference,
    ) -> None:
        target = self._credential_path(
            organization_public_id=organization_public_id,
            provider_id=provider_id,
            credential_reference=credential_reference,
        )
        async with self._lock:
            try:
                await asyncio.to_thread(target.unlink, missing_ok=True)
            except OSError:
                raise CredentialStoreError("Credential could not be deleted.") from None

    def _atomic_write(self, target: Path, ciphertext: bytes) -> None:
        self._path.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self._path / f".{target.name}.{uuid4().hex}.tmp"
        descriptor: int | None = None
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                stream.write(ciphertext)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)
