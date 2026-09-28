"""Optional provider-credential storage composition and lifecycle."""

from __future__ import annotations

from asyncio import CancelledError
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from azure.identity.aio import ManagedIdentityCredential
from azure.keyvault.secrets.aio import SecretClient

from nexus.config.settings import Settings
from nexus.infrastructure.credentials import (
    AzureKeyVaultCredentialStore,
    LocalEncryptedCredentialStore,
)
from nexus.model_providers.ports import CredentialStore

_LOCAL_ENVIRONMENTS = frozenset({"development", "test"})
_INVALID_VAULT_URL = "Azure Key Vault URL must be a credential-free HTTPS root"

type AsyncCloseCallback = Callable[[], Awaitable[None]]


class CredentialStoreConfigurationError(ValueError):
    """Raised when an explicitly configured credential store is unsafe."""


async def _noop_close() -> None:
    return None


@dataclass(frozen=True)
class ProviderCredentialComposition:
    """Optional credential store plus application-owned provider resources."""

    store: CredentialStore | None
    _close_callback: AsyncCloseCallback = field(default=_noop_close, repr=False)

    async def close(self) -> None:
        await self._close_callback()


async def _close_azure_resources(
    secret_client: SecretClient | None,
    credential: ManagedIdentityCredential | None,
) -> None:
    if secret_client is not None:
        try:
            await secret_client.close()
        finally:
            if credential is not None:
                await credential.close()
    elif credential is not None:
        await credential.close()


def _validated_vault_url(settings: Settings) -> str:
    url = settings.azure_key_vault_url
    if url is None:
        raise CredentialStoreConfigurationError("Azure Key Vault URL is not configured")
    if (
        url.scheme != "https"
        or url.username is not None
        or url.password is not None
        or url.path != "/"
        or url.query is not None
        or url.fragment is not None
    ):
        raise CredentialStoreConfigurationError(_INVALID_VAULT_URL)
    return str(url)


async def build_provider_credential_composition(
    settings: Settings,
    *,
    credential_store: CredentialStore | None = None,
) -> ProviderCredentialComposition:
    """Compose a configured store, or no store when the feature is disabled."""

    if credential_store is not None:
        if isinstance(credential_store, LocalEncryptedCredentialStore) and (
            settings.app_env not in _LOCAL_ENVIRONMENTS
        ):
            raise CredentialStoreConfigurationError(
                "Local credential storage is restricted to development and test"
            )
        return ProviderCredentialComposition(store=credential_store)

    provider = settings.credential_store_provider
    if provider is None:
        return ProviderCredentialComposition(store=None)

    if provider == "local_encrypted":
        if settings.app_env not in _LOCAL_ENVIRONMENTS:
            raise CredentialStoreConfigurationError(
                "Local credential storage is restricted to development and test"
            )
        if settings.local_credential_store_path is None:
            raise CredentialStoreConfigurationError(
                "Local credential storage path is not configured"
            )
        if settings.local_credential_store_key is None:
            raise CredentialStoreConfigurationError(
                "Local credential encryption key is not configured"
            )
        if (
            settings.azure_key_vault_url is not None
            or settings.azure_key_vault_managed_identity_client_id is not None
        ):
            raise CredentialStoreConfigurationError(
                "Credential store configuration mixes provider settings"
            )
        try:
            local_store = LocalEncryptedCredentialStore(
                path=settings.local_credential_store_path,
                encryption_key=settings.local_credential_store_key,
            )
        except ValueError:
            raise CredentialStoreConfigurationError(
                "Local credential encryption key is invalid"
            ) from None
        return ProviderCredentialComposition(store=local_store)

    if provider != "azure_key_vault":
        raise CredentialStoreConfigurationError(
            "Unsupported credential store provider configuration"
        )

    if (
        settings.local_credential_store_path is not None
        or settings.local_credential_store_key is not None
    ):
        raise CredentialStoreConfigurationError(
            "Credential store configuration mixes provider settings"
        )

    vault_url = _validated_vault_url(settings)
    credential: ManagedIdentityCredential | None = None
    secret_client: SecretClient | None = None
    try:
        client_id = settings.azure_key_vault_managed_identity_client_id
        credential = (
            ManagedIdentityCredential(client_id=str(client_id))
            if client_id is not None
            else ManagedIdentityCredential()
        )
        secret_client = SecretClient(vault_url=vault_url, credential=credential)
        azure_store = AzureKeyVaultCredentialStore(secret_client)
    except (Exception, CancelledError) as construction_error:
        try:
            await _close_azure_resources(secret_client, credential)
        except (Exception, CancelledError) as cleanup_error:  # noqa: BLE001
            construction_error.add_note(
                "A credential-store resource also failed during startup cleanup: "
                f"{type(cleanup_error).__name__}"
            )
        raise

    async def close_resources() -> None:
        await _close_azure_resources(secret_client, credential)

    return ProviderCredentialComposition(
        store=azure_store,
        _close_callback=close_resources,
    )
