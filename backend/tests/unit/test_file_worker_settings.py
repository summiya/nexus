from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.config.file_worker_settings import FileWorkerSettings

DEVELOPMENT_CONTEXT_KEY = "bmV4dXMtZGV2ZWxvcG1lbnQtdXBsb2FkLWtleS0wMDE"
PRODUCTION_CONTEXT_KEY = "ZW52LWZpbGUtdXBsb2FkLWNvbnRleHQta2V5LTAwMDE"


def _settings(**changes: object) -> FileWorkerSettings:
    values = {
        "database_url": "postgresql://nexus:nexus@postgres:5432/nexus",
        "file_upload_context_key": DEVELOPMENT_CONTEXT_KEY,
        "azure_service_bus_fully_qualified_namespace": ("nexus.servicebus.windows.net"),
        "azure_service_bus_queue_name": "file-upload-completions",
        "azure_event_grid_expected_source": (
            "/subscriptions/test/resourceGroups/nexus/providers/"
            "Microsoft.Storage/storageAccounts/nexus"
        ),
        "azure_malware_scan_expected_topic": (
            "/subscriptions/test/resourceGroups/nexus/providers/"
            "Microsoft.EventGrid/topics/nexus-file-malware-scan-results"
        ),
        "azure_storage_container": "nexus-files",
        "azure_storage_account_url": "https://nexus.blob.core.windows.net",
        **changes,
    }
    return FileWorkerSettings(_env_file=None, **values)


def test_worker_settings_have_narrow_safe_defaults() -> None:
    settings = _settings()

    assert settings.file_upload_completion_source == "azure-primary"
    assert settings.file_malware_scan_source == "azure-defender-storage"
    assert settings.azure_service_bus_malware_scan_queue_name == (
        "file-malware-scan-results"
    )
    assert settings.file_worker_max_lock_renewal_seconds == 300
    assert settings.log_level == "INFO"
    assert settings.file_upload_max_size_bytes == 536_870_912
    assert settings.file_worker_database_pool_size == 2
    assert settings.file_worker_database_max_overflow == 0
    assert settings.azure_service_bus_managed_identity_client_id is None
    assert not hasattr(settings, "redis_url")
    assert not hasattr(settings, "azure_service_bus_connection_string")


def test_worker_settings_accept_user_assigned_managed_identity() -> None:
    client_id = UUID("11111111-1111-4111-8111-111111111111")

    settings = _settings(
        azure_service_bus_managed_identity_client_id=client_id,
    )

    assert settings.azure_service_bus_managed_identity_client_id == client_id


@pytest.mark.parametrize(
    "namespace",
    [
        "",
        " https://nexus.servicebus.windows.net",
        "https://nexus.servicebus.windows.net",
        "nexus.servicebus.windows.net/path",
        "nexus.servicebus.windows.net?key=value",
        "nexus servicebus.windows.net",
    ],
)
def test_worker_settings_reject_invalid_namespace(namespace: str) -> None:
    with pytest.raises(ValidationError):
        _settings(azure_service_bus_fully_qualified_namespace=namespace)


@pytest.mark.parametrize("seconds", [59, 601])
def test_worker_settings_bound_lock_renewal(seconds: int) -> None:
    with pytest.raises(ValidationError):
        _settings(file_worker_max_lock_renewal_seconds=seconds)


def test_worker_settings_require_event_source_queue_and_container() -> None:
    for field_name in (
        "azure_service_bus_queue_name",
        "azure_event_grid_expected_source",
        "azure_malware_scan_expected_topic",
        "azure_storage_container",
    ):
        with pytest.raises(ValidationError):
            _settings(**{field_name: ""})


def test_production_rejects_repository_development_context_key() -> None:
    with pytest.raises(ValidationError) as captured:
        _settings(app_env="production")

    assert "Production File upload context key must be overridden" in str(
        captured.value
    )
    assert DEVELOPMENT_CONTEXT_KEY not in str(captured.value)

    settings = _settings(
        app_env="production",
        file_upload_context_key=PRODUCTION_CONTEXT_KEY,
    )
    assert settings.app_env == "production"


@pytest.mark.parametrize(
    "account_url",
    [
        "http://nexus.blob.core.windows.net",
        "https://user:password@nexus.blob.core.windows.net",
        "https://nexus.blob.core.windows.net/container",
        "https://nexus.blob.core.windows.net?sig=secret",
        "https://nexus.blob.core.windows.net#fragment",
    ],
)
def test_worker_rejects_non_root_or_credential_bearing_storage_url(
    account_url: str,
) -> None:
    with pytest.raises(ValidationError):
        _settings(azure_storage_account_url=account_url)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("file_worker_database_pool_size", 0),
        ("file_worker_database_max_overflow", -1),
    ],
)
def test_worker_database_pool_settings_are_bounded(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        _settings(**{field: value})
