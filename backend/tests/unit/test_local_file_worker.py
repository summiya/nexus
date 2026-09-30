from __future__ import annotations

import pytest
from pydantic import ValidationError

from nexus.dev.local_file_worker import LocalFileWorkerSettings

CONTEXT_KEY = "bmV4dXMtZGV2ZWxvcG1lbnQtdXBsb2FkLWtleS0wMDE"


def _settings(**overrides: object) -> LocalFileWorkerSettings:
    values: dict[str, object] = {
        "app_env": "development",
        "database_url": "postgresql://nexus:nexus@postgres:5432/nexus",
        "file_upload_context_key": CONTEXT_KEY,
        "azure_storage_connection_string": "UseDevelopmentStorage=true",
        "azure_storage_container": "nexus-files",
        "azure_storage_account_name": "devstoreaccount1",
        "azure_service_bus_connection_string": (
            "Endpoint=sb://servicebus-emulator;"
            "SharedAccessKeyName=RootManageSharedAccessKey;"
            "SharedAccessKey=SAS_KEY_VALUE;"
            "UseDevelopmentEmulator=true;"
        ),
        "azure_service_bus_queue_name": "file-upload-completions",
        "azure_service_bus_malware_scan_queue_name": "file-malware-scan-results",
        "azure_event_grid_expected_source": "/local/azurite",
        "azure_malware_scan_expected_topic": "/local/defender",
        **overrides,
    }
    return LocalFileWorkerSettings(_env_file=None, **values)


def test_local_worker_accepts_development_emulator_configuration() -> None:
    settings = _settings()

    assert settings.app_env == "development"
    assert settings.azure_storage_account_name == "devstoreaccount1"
    assert settings.file_upload_completion_source == "local-azurite"
    assert settings.file_malware_scan_source == "local-malware-simulator"


@pytest.mark.parametrize("environment", ["production", "staging", "local", "DEVELOPMENT"])
def test_local_worker_rejects_non_local_environments(environment: str) -> None:
    with pytest.raises(ValidationError, match="restricted to development and test"):
        _settings(app_env=environment)


@pytest.mark.parametrize(
    "field",
    [
        "azure_storage_container",
        "azure_storage_account_name",
        "azure_service_bus_queue_name",
        "azure_service_bus_malware_scan_queue_name",
        "azure_event_grid_expected_source",
        "azure_malware_scan_expected_topic",
    ],
)
def test_local_worker_rejects_blank_transport_identifiers(field: str) -> None:
    with pytest.raises(ValidationError):
        _settings(**{field: " "})
