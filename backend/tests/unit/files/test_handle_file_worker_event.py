from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from nexus.files.application import HandleFileWorkerEvent
from nexus.files.ports import (
    MalwareScanResultEvent,
    MalwareScanVerdict,
    UploadCompletionEvent,
)

STORAGE_KEY = "files/0123456789abcdef0123456789abcdef"
NOW = datetime(2026, 9, 26, tzinfo=UTC)


class RecordingUploadHandler:
    def __init__(self) -> None:
        self.events: list[UploadCompletionEvent] = []

    async def handle(self, event: UploadCompletionEvent) -> None:
        self.events.append(event)


class RecordingMalwareHandler:
    def __init__(self) -> None:
        self.events: list[MalwareScanResultEvent] = []

    async def handle(self, event: MalwareScanResultEvent) -> None:
        self.events.append(event)


def test_dispatches_each_file_worker_event_to_one_handler() -> None:
    upload = RecordingUploadHandler()
    malware = RecordingMalwareHandler()
    dispatcher = HandleFileWorkerEvent(upload, malware)

    upload_event = UploadCompletionEvent(
        event_id="upload-1",
        source="azure-primary",
        storage_key=STORAGE_KEY,
        occurred_at=NOW,
        entity_tag="etag",
        reported_size_bytes=1,
    )
    malware_event = MalwareScanResultEvent(
        event_id="scan-1",
        source="azure-defender-storage",
        storage_key=STORAGE_KEY,
        occurred_at=NOW,
        entity_tag="etag",
        verdict=MalwareScanVerdict.CLEAN,
    )

    asyncio.run(dispatcher.handle(upload_event))
    asyncio.run(dispatcher.handle(malware_event))

    assert upload.events == [upload_event]
    assert malware.events == [malware_event]
