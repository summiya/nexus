from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from nexus.dev import local_file_events
from nexus.infrastructure.messaging.azure_service_bus_publisher import (
    AzureServiceBusPublicationError,
)


@pytest.mark.parametrize(
    "failure", [None, RuntimeError("transient"), AzureServiceBusPublicationError()]
)
def test_send_delegates_exact_message_and_owns_client(monkeypatch, failure):
    async def run():
        monkeypatch.setenv("AZURE_SERVICE_BUS_CONNECTION_STRING", "local-connection")
        client = AsyncMock()
        client.__aenter__.return_value = client
        factory = MagicMock(return_value=client)
        monkeypatch.setattr(
            local_file_events.ServiceBusClient, "from_connection_string", factory
        )
        publisher = AsyncMock()
        publisher.publish.side_effect = failure
        constructor = MagicMock(return_value=publisher)
        monkeypatch.setattr(
            local_file_events, "AzureServiceBusQueuePublisher", constructor
        )
        payload = {"id": 123, "data": {"name": "café", "size": 7}}
        if failure is None:
            await local_file_events._send("selected-local-queue", payload)
            client.__aexit__.assert_awaited_once_with(None, None, None)
        else:
            with pytest.raises(type(failure)) as exc:
                await local_file_events._send("selected-local-queue", payload)
            assert exc.value is failure
            client.__aexit__.assert_awaited_once()
            assert client.__aexit__.await_args.args[:2] == (type(failure), failure)
        factory.assert_called_once_with("local-connection")
        constructor.assert_called_once_with(client)
        client.__aenter__.assert_awaited_once_with()
        publisher.publish.assert_awaited_once_with(
            queue_name="selected-local-queue",
            body=b'{"id":123,"data":{"name":"caf\\u00e9","size":7}}',
            message_id="123",
            content_type="application/json",
        )
        client.get_queue_sender.assert_not_called()

    asyncio.run(run())


def test_cancellation_propagates_and_exits_owned_client(monkeypatch):
    async def run():
        monkeypatch.setenv("AZURE_SERVICE_BUS_CONNECTION_STRING", "local-connection")
        client = AsyncMock()
        client.__aenter__.return_value = client
        monkeypatch.setattr(
            local_file_events.ServiceBusClient,
            "from_connection_string",
            MagicMock(return_value=client),
        )
        started = asyncio.Event()

        async def publish(**kwargs):
            started.set()
            await asyncio.Future()

        publisher = AsyncMock()
        publisher.publish.side_effect = publish
        monkeypatch.setattr(
            local_file_events,
            "AzureServiceBusQueuePublisher",
            MagicMock(return_value=publisher),
        )
        task = asyncio.create_task(local_file_events._send("queue", {"id": "event"}))
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError) as exc:
            await task
        client.__aexit__.assert_awaited_once()
        assert client.__aexit__.await_args.args[:2] == (
            asyncio.CancelledError,
            exc.value,
        )

    asyncio.run(run())


@pytest.mark.parametrize("event", ["upload", "malware"])
def test_file_event_payload_and_queue_are_preserved(monkeypatch, event):
    async def run():
        monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "local-storage")
        monkeypatch.setenv("AZURE_STORAGE_CONTAINER", "custom-files")
        monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_NAME", "custom-account")
        event_id = UUID("00000000-0000-0000-0000-000000000001")
        monkeypatch.setattr(local_file_events, "uuid4", lambda: event_id)
        clock = MagicMock()
        clock.now.return_value = datetime(2026, 10, 5, 12, 30, tzinfo=UTC)
        monkeypatch.setattr(local_file_events, "datetime", clock)
        service = AsyncMock()
        service.__aenter__.return_value = service
        container = MagicMock()
        blob = AsyncMock()
        blob.get_blob_properties.return_value = SimpleNamespace(
            etag='"verified-etag"', size=42
        )
        container.get_blob_client.return_value = blob
        service.get_container_client = MagicMock(return_value=container)
        factory = MagicMock(return_value=service)
        monkeypatch.setattr(
            local_file_events.BlobServiceClient, "from_connection_string", factory
        )
        send = AsyncMock()
        monkeypatch.setattr(local_file_events, "_send", send)
        if event == "upload":
            key = await local_file_events._emit_upload_completed("tenant/source.txt")
            send.assert_awaited_once_with(
                "file-upload-completions",
                {
                    "specversion": "1.0",
                    "type": "Microsoft.Storage.BlobCreated",
                    "source": "/local/azurite",
                    "id": str(event_id),
                    "time": "2026-10-05T12:30:00Z",
                    "subject": "/blobServices/default/containers/custom-files/blobs/tenant/source.txt",
                    "data": {
                        "api": "PutBlob",
                        "blobType": "BlockBlob",
                        "eTag": "verified-etag",
                        "contentLength": 42,
                    },
                },
            )
        else:
            key = await local_file_events._emit_malware(
                "tenant/source.txt", "Malicious"
            )
            send.assert_awaited_once_with(
                "file-malware-scan-results",
                {
                    "id": str(event_id),
                    "topic": "/local/defender",
                    "subject": "storageAccounts/custom-account/containers/custom-files/blobs/tenant/source.txt",
                    "eventType": "Microsoft.Security.MalwareScanningResult",
                    "eventTime": "2026-10-05T12:30:00Z",
                    "dataVersion": "1.0",
                    "metadataVersion": "1",
                    "data": {"eTag": '"verified-etag"', "scanResultType": "Malicious"},
                },
            )
        assert key == "tenant/source.txt"
        factory.assert_called_once_with("local-storage")
        service.get_container_client.assert_called_once_with("custom-files")
        container.get_blob_client.assert_called_once_with("tenant/source.txt")
        blob.get_blob_properties.assert_awaited_once_with()
        clock.now.assert_called_once_with(UTC)
        service.__aexit__.assert_awaited_once_with(None, None, None)

    asyncio.run(run())
