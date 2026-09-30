"""Emit local Azure-shaped File events through the Service Bus emulator."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from uuid import uuid4

from azure.servicebus import ServiceBusMessage
from azure.servicebus.aio import ServiceBusClient
from azure.storage.blob.aio import BlobServiceClient

from nexus.infrastructure.storage.azure_blob import normalize_azure_entity_tag

_DEFAULT_CONTAINER = "nexus-files"
_UPLOAD_QUEUE = "file-upload-completions"
_MALWARE_QUEUE = "file-malware-scan-results"
_EVENT_SOURCE = "/local/azurite"
_MALWARE_TOPIC = "/local/defender"
_ACCOUNT_NAME = "devstoreaccount1"


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


async def _latest_storage_key(container_client: object) -> str:
    latest_name: str | None = None
    latest_modified: datetime | None = None
    async for blob in container_client.list_blobs():  # type: ignore[attr-defined]
        modified = blob.last_modified
        if latest_modified is None or modified > latest_modified:
            latest_modified = modified
            latest_name = blob.name
    if latest_name is None:
        raise RuntimeError("No blobs exist in the local container")
    return latest_name


async def _resolve_blob(container_client: object, storage_key: str | None):
    key = storage_key or await _latest_storage_key(container_client)
    client = container_client.get_blob_client(key)  # type: ignore[attr-defined]
    properties = await client.get_blob_properties()
    return key, properties


async def _send(queue_name: str, payload: dict[str, object]) -> None:
    connection_string = _required_env("AZURE_SERVICE_BUS_CONNECTION_STRING")
    async with (
        ServiceBusClient.from_connection_string(connection_string) as client,
        client.get_queue_sender(queue_name=queue_name) as sender,
    ):
        await sender.send_messages(
            ServiceBusMessage(
                json.dumps(payload, separators=(",", ":")),
                message_id=str(payload["id"]),
                content_type="application/json",
            )
        )


async def _emit_upload_completed(storage_key: str | None) -> str:
    storage_connection = _required_env("AZURE_STORAGE_CONNECTION_STRING")
    container_name = os.environ.get("AZURE_STORAGE_CONTAINER", _DEFAULT_CONTAINER)
    async with BlobServiceClient.from_connection_string(storage_connection) as service:
        container = service.get_container_client(container_name)
        key, properties = await _resolve_blob(container, storage_key)

    event_id = str(uuid4())
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    payload: dict[str, object] = {
        "specversion": "1.0",
        "type": "Microsoft.Storage.BlobCreated",
        "source": _EVENT_SOURCE,
        "id": event_id,
        "time": now,
        "subject": f"/blobServices/default/containers/{container_name}/blobs/{key}",
        "data": {
            "api": "PutBlob",
            "blobType": "BlockBlob",
            "eTag": normalize_azure_entity_tag(properties.etag),
            "contentLength": properties.size,
        },
    }
    await _send(_UPLOAD_QUEUE, payload)
    return key


async def _emit_malware(storage_key: str | None, verdict: str) -> str:
    storage_connection = _required_env("AZURE_STORAGE_CONNECTION_STRING")
    container_name = os.environ.get("AZURE_STORAGE_CONTAINER", _DEFAULT_CONTAINER)
    account_name = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME", _ACCOUNT_NAME)
    async with BlobServiceClient.from_connection_string(storage_connection) as service:
        container = service.get_container_client(container_name)
        key, properties = await _resolve_blob(container, storage_key)

    event_id = str(uuid4())
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    payload: dict[str, object] = {
        "id": event_id,
        "topic": _MALWARE_TOPIC,
        "subject": (
            f"storageAccounts/{account_name}/containers/{container_name}/blobs/{key}"
        ),
        "eventType": "Microsoft.Security.MalwareScanningResult",
        "eventTime": now,
        "dataVersion": "1.0",
        "metadataVersion": "1",
        "data": {
            "eTag": properties.etag,
            "scanResultType": verdict,
        },
    }
    await _send(_MALWARE_QUEUE, payload)
    return key


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    upload = subparsers.add_parser("upload-completed")
    upload.add_argument("--storage-key")

    malware = subparsers.add_parser("malware")
    malware.add_argument("--storage-key")
    malware.add_argument(
        "--verdict",
        choices=["No threats found", "Malicious", "Not Scanned", "Error"],
        default="No threats found",
    )
    return parser


async def _run() -> None:
    args = _parser().parse_args()
    if args.command == "upload-completed":
        key = await _emit_upload_completed(args.storage_key)
        print(f"Published upload completion for {key}")
        return
    key = await _emit_malware(args.storage_key, args.verdict)
    print(f"Published malware result for {key}: {args.verdict}")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
