from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast

from nexus.files.ports import MalwareScanResultEvent, UploadCompletionEvent
from nexus.infrastructure.storage import (
    AzureBlobCreatedEventMapper,
    AzureFileWorkerEventMapper,
    AzureMalwareScanResultMapper,
)

AZURE_SOURCE = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/"
    "resourceGroups/nexus/providers/Microsoft.Storage/storageAccounts/nexus"
)
TOPIC = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/"
    "resourceGroups/nexus/providers/Microsoft.EventGrid/topics/scan"
)
STORAGE_KEY = "files/0123456789abcdef0123456789abcdef"


def _router() -> AzureFileWorkerEventMapper:
    return AzureFileWorkerEventMapper(
        blob_created_mapper=AzureBlobCreatedEventMapper(
            expected_source=AZURE_SOURCE,
            expected_container="nexus-files",
            nexus_source="azure-primary",
        ),
        malware_scan_mapper=AzureMalwareScanResultMapper(
            expected_topic=TOPIC,
            expected_storage_account="nexus",
            expected_container="nexus-files",
        ),
    )


def test_routes_blob_created_and_malware_result_shapes() -> None:
    blob_payload: Mapping[str, object] = {
        "specversion": "1.0",
        "type": "Microsoft.Storage.BlobCreated",
        "source": AZURE_SOURCE,
        "id": "blob-1",
        "time": "2026-09-26T00:00:00Z",
        "subject": f"/blobServices/default/containers/nexus-files/blobs/{STORAGE_KEY}",
        "data": {
            "api": "PutBlob",
            "blobType": "BlockBlob",
            "eTag": "etag",
            "contentLength": 1,
        },
    }
    malware_payload: Mapping[str, object] = {
        "id": "scan-1",
        "subject": f"storageAccounts/nexus/containers/nexus-files/blobs/{STORAGE_KEY}",
        "data": {
            "eTag": "etag",
            "scanResultType": "No threats found",
        },
        "eventType": "Microsoft.Security.MalwareScanningResult",
        "dataVersion": "1.0",
        "metadataVersion": "1",
        "eventTime": datetime(2026, 9, 26, tzinfo=UTC).isoformat(),
        "topic": TOPIC,
    }

    assert isinstance(_router().map_event(blob_payload), UploadCompletionEvent)
    assert isinstance(_router().map_event(malware_payload), MalwareScanResultEvent)
