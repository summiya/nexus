from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.config.file_worker_settings import FileWorkerSettings


def _settings(**changes: object) -> FileWorkerSettings:
    values = {
        "azure_service_bus_fully_qualified_namespace": ("nexus.servicebus.windows.net"),
        "azure_service_bus_queue_name": "file-upload-completions",
        "azure_event_grid_expected_source": (
            "/subscriptions/test/resourceGroups/nexus/providers/"
            "Microsoft.Storage/storageAccounts/nexus"
        ),
        "azure_storage_container": "nexus-files",
        **changes,
    }
    return FileWorkerSettings(_env_file=None, **values)


def test_worker_settings_have_narrow_safe_defaults() -> None:
    settings = _settings()

    assert settings.file_upload_completion_source == "azure-primary"
    assert settings.file_worker_max_lock_renewal_seconds == 300
    assert settings.log_level == "INFO"
    assert settings.azure_service_bus_managed_identity_client_id is None
    assert not hasattr(settings, "database_url")
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
        "azure_storage_container",
    ):
        with pytest.raises(ValidationError):
            _settings(**{field_name: ""})
