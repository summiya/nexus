"""Application-scoped object storage composition and lifecycle."""

from __future__ import annotations

from asyncio import CancelledError
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime

from azure.identity.aio import ManagedIdentityCredential
from azure.storage.blob.aio import BlobServiceClient

from nexus.config.settings import Settings
from nexus.files.ports import (
    ObjectStorage,
    UploadGrant,
    UploadGrantError,
    UploadGrantIssuer,
)
from nexus.infrastructure.storage import (
    AzureBlobObjectStorage,
    AzureUserDelegationUploadGrantIssuer,
)

_LOCAL_CONNECTION_STRING_ENVIRONMENTS = frozenset({"development", "test"})
_INVALID_ACCOUNT_URL_MESSAGE = (
    "Azure storage account URL must be a credential-free HTTPS service root"
)

type AsyncCloseCallback = Callable[[], Awaitable[None]]


class StorageConfigurationError(ValueError):
    """Raised when object storage configuration is invalid or unsupported."""


class _UnavailableUploadGrantIssuer:
    """Fail safely where the configured storage auth cannot issue upload grants."""

    async def issue_upload_grant(
        self,
        *,
        storage_key: str,
        expires_at: datetime,
    ) -> UploadGrant:
        del storage_key, expires_at
        raise UploadGrantError("Upload grants are unavailable")


async def _noop_close() -> None:
    return None


async def _close_azure_resources(
    service_client: BlobServiceClient | None,
    credential: ManagedIdentityCredential | None,
) -> None:
    if service_client is None:
        if credential is not None:
            await credential.close()
        return

    try:
        await service_client.close()
    finally:
        if credential is not None:
            await credential.close()


@dataclass(frozen=True)
class StorageComposition:
    """Application-owned storage ports and provider-resource cleanup."""

    object_storage: ObjectStorage
    upload_grant_issuer: UploadGrantIssuer
    _close_callback: AsyncCloseCallback = field(
        default=_noop_close,
        repr=False,
    )

    async def close(self) -> None:
        """Release application-owned provider resources."""

        await self._close_callback()


def _azure_configuration(
    settings: Settings,
) -> tuple[str, str | None, str | None]:
    if settings.storage_provider.strip() != "azure_blob":
        raise StorageConfigurationError("Unsupported storage provider configuration")

    container_name = (settings.azure_storage_container or "").strip()
    if not container_name:
        raise StorageConfigurationError("Azure storage container is not configured")

    configured_connection_string = settings.azure_storage_connection_string
    connection_string = (
        configured_connection_string.get_secret_value().strip()
        if configured_connection_string is not None
        else None
    )
    if configured_connection_string is not None and not connection_string:
        raise StorageConfigurationError(
            "Azure storage connection string must not be blank"
        )

    account_url = (
        str(settings.azure_storage_account_url)
        if settings.azure_storage_account_url is not None
        else None
    )
    if connection_string is not None and account_url is not None:
        raise StorageConfigurationError(
            "Configure exactly one Azure storage authentication mode"
        )
    if connection_string is None and account_url is None:
        raise StorageConfigurationError(
            "Azure storage authentication is not configured"
        )

    if (
        settings.azure_storage_managed_identity_client_id is not None
        and account_url is None
    ):
        raise StorageConfigurationError(
            "Managed Identity client ID requires an Azure storage account URL"
        )

    if connection_string is not None:
        if settings.app_env not in _LOCAL_CONNECTION_STRING_ENVIRONMENTS:
            raise StorageConfigurationError(
                "Azure storage connection strings are restricted to development "
                "and test environments"
            )
        return container_name, connection_string, None

    if settings.azure_storage_account_url is None:
        raise StorageConfigurationError("Azure storage account URL is not configured")
    if (
        settings.azure_storage_account_url.scheme != "https"
        or settings.azure_storage_account_url.username is not None
        or settings.azure_storage_account_url.password is not None
        or settings.azure_storage_account_url.path != "/"
        or settings.azure_storage_account_url.query is not None
        or settings.azure_storage_account_url.fragment is not None
    ):
        raise StorageConfigurationError(_INVALID_ACCOUNT_URL_MESSAGE)
    return container_name, None, account_url


async def build_storage_composition(
    settings: Settings,
    *,
    object_storage: ObjectStorage | None = None,
    upload_grant_issuer: UploadGrantIssuer | None = None,
) -> StorageComposition:
    """Build provider-neutral storage dependencies and own their resources."""

    if object_storage is not None:
        return StorageComposition(
            object_storage=object_storage,
            upload_grant_issuer=(
                upload_grant_issuer
                if upload_grant_issuer is not None
                else _UnavailableUploadGrantIssuer()
            ),
        )

    container_name, connection_string, account_url = _azure_configuration(settings)
    account_name: str | None = None
    if upload_grant_issuer is None and account_url is not None:
        account_name = (settings.azure_storage_account_name or "").strip()
        if not account_name:
            raise StorageConfigurationError(
                "Azure storage account name is not configured"
            )

    credential: ManagedIdentityCredential | None = None
    service_client: BlobServiceClient | None = None
    try:
        if connection_string is not None:
            service_client = BlobServiceClient.from_connection_string(connection_string)
        else:
            assert account_url is not None
            client_id = settings.azure_storage_managed_identity_client_id
            credential = (
                ManagedIdentityCredential(client_id=str(client_id))
                if client_id is not None
                else ManagedIdentityCredential()
            )
            service_client = BlobServiceClient(
                account_url=account_url,
                credential=credential,
            )
        container_client = service_client.get_container_client(container_name)
        resolved_storage = AzureBlobObjectStorage(container_client)
        if upload_grant_issuer is not None:
            resolved_upload_grant_issuer = upload_grant_issuer
        elif connection_string is not None:
            resolved_upload_grant_issuer = _UnavailableUploadGrantIssuer()
        else:
            assert account_name is not None
            resolved_upload_grant_issuer = AzureUserDelegationUploadGrantIssuer(
                service_client,
                account_name=account_name,
                container_name=container_name,
            )
    except (Exception, CancelledError) as construction_error:
        try:
            await _close_azure_resources(service_client, credential)
        except (Exception, CancelledError) as cleanup_error:  # noqa: BLE001 - preserve startup failure
            construction_error.add_note(
                "An object storage resource also failed during startup cleanup: "
                f"{type(cleanup_error).__name__}"
            )
        raise

    async def close_resources() -> None:
        await _close_azure_resources(service_client, credential)

    return StorageComposition(
        object_storage=resolved_storage,
        upload_grant_issuer=resolved_upload_grant_issuer,
        _close_callback=close_resources,
    )
