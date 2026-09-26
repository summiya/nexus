"""Route supported Azure File events into provider-neutral contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from nexus.files.application.handle_file_worker_event import FileWorkerEvent
from nexus.infrastructure.storage.azure_blob_created import AzureBlobCreatedEventMapper
from nexus.infrastructure.storage.azure_malware_scan import AzureMalwareScanResultMapper

_MALWARE_EVENT_TYPE = "Microsoft.Security.MalwareScanningResult"


@dataclass(frozen=True)
class AzureFileWorkerEventMapper:
    """Select the strict Azure mapper for one supported File event shape."""

    blob_created_mapper: AzureBlobCreatedEventMapper
    malware_scan_mapper: AzureMalwareScanResultMapper

    def map_event(self, payload: Mapping[str, object]) -> FileWorkerEvent:
        if payload.get("eventType") == _MALWARE_EVENT_TYPE:
            return self.malware_scan_mapper.map_event(payload)
        return self.blob_created_mapper.map_event(payload)


__all__ = ["AzureFileWorkerEventMapper"]
