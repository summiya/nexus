from __future__ import annotations

import asyncio
import stat
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from nexus.infrastructure.credentials import LocalEncryptedCredentialStore
from nexus.model_providers.domain import (
    CredentialReference,
    OrganizationProviderId,
    ProviderCredentialSecret,
)
from nexus.model_providers.ports import CredentialNotFoundError, CredentialStoreError


def _store(path: Path, key: bytes) -> LocalEncryptedCredentialStore:
    return LocalEncryptedCredentialStore(
        path=path,
        encryption_key=SecretStr(key.decode("ascii")),
    )


def test_local_store_create_resolve_replace_delete_and_encryption(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        store = _store(tmp_path, Fernet.generate_key())
        organization_id = uuid4()
        provider_id = OrganizationProviderId(uuid4())
        reference = CredentialReference(uuid4())
        first_plaintext = "first-super-secret"
        second_plaintext = "second-super-secret"

        await store.put(
            organization_public_id=organization_id,
            provider_id=provider_id,
            credential_reference=reference,
            secret=ProviderCredentialSecret(first_plaintext),
        )
        credential_file = next(tmp_path.iterdir())
        persisted = credential_file.read_bytes()
        assert first_plaintext.encode() not in persisted
        assert stat.S_IMODE(credential_file.stat().st_mode) == 0o600
        assert (
            await store.resolve(
                organization_public_id=organization_id,
                provider_id=provider_id,
                credential_reference=reference,
            )
        ).reveal() == first_plaintext

        await store.put(
            organization_public_id=organization_id,
            provider_id=provider_id,
            credential_reference=reference,
            secret=ProviderCredentialSecret(second_plaintext),
        )
        assert len(list(tmp_path.iterdir())) == 1
        assert (
            await store.resolve(
                organization_public_id=organization_id,
                provider_id=provider_id,
                credential_reference=reference,
            )
        ).reveal() == second_plaintext

        await store.delete(
            organization_public_id=organization_id,
            provider_id=provider_id,
            credential_reference=reference,
        )
        await store.delete(
            organization_public_id=organization_id,
            provider_id=provider_id,
            credential_reference=reference,
        )
        with pytest.raises(CredentialNotFoundError):
            await store.resolve(
                organization_public_id=organization_id,
                provider_id=provider_id,
                credential_reference=reference,
            )

    asyncio.run(scenario())


def test_local_store_scopes_credentials_by_all_three_identities(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = _store(tmp_path, Fernet.generate_key())
        organization_id = uuid4()
        provider_id = OrganizationProviderId(uuid4())
        reference = CredentialReference(uuid4())
        await store.put(
            organization_public_id=organization_id,
            provider_id=provider_id,
            credential_reference=reference,
            secret=ProviderCredentialSecret("secret"),
        )

        for wrong_organization, wrong_provider, wrong_reference in (
            (uuid4(), provider_id, reference),
            (organization_id, OrganizationProviderId(uuid4()), reference),
            (organization_id, provider_id, CredentialReference(uuid4())),
        ):
            with pytest.raises(CredentialNotFoundError):
                await store.resolve(
                    organization_public_id=wrong_organization,
                    provider_id=wrong_provider,
                    credential_reference=wrong_reference,
                )

    asyncio.run(scenario())


def test_wrong_key_and_corrupted_ciphertext_fail_safely(tmp_path: Path) -> None:
    async def scenario() -> None:
        organization_id = uuid4()
        provider_id = OrganizationProviderId(uuid4())
        reference = CredentialReference(uuid4())
        original = _store(tmp_path, Fernet.generate_key())
        plaintext = "must-never-leak"
        await original.put(
            organization_public_id=organization_id,
            provider_id=provider_id,
            credential_reference=reference,
            secret=ProviderCredentialSecret(plaintext),
        )

        wrong_key = _store(tmp_path, Fernet.generate_key())
        with pytest.raises(CredentialStoreError) as wrong_key_error:
            await wrong_key.resolve(
                organization_public_id=organization_id,
                provider_id=provider_id,
                credential_reference=reference,
            )
        assert plaintext not in str(wrong_key_error.value)

        next(tmp_path.iterdir()).write_bytes(b"corrupted")
        with pytest.raises(CredentialStoreError) as corrupt_error:
            await original.resolve(
                organization_public_id=organization_id,
                provider_id=provider_id,
                credential_reference=reference,
            )
        assert plaintext not in str(corrupt_error.value)

    asyncio.run(scenario())
