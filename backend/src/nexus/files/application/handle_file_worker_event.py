"""Dispatch File worker events to their application handlers."""

from __future__ import annotations

from dataclasses import dataclass

from nexus.files.ports import (
    MalwareScanResultEvent,
    MalwareScanResultHandler,
    UploadCompletionEvent,
    UploadCompletionHandler,
)

type FileWorkerEvent = UploadCompletionEvent | MalwareScanResultEvent


@dataclass(frozen=True)
class HandleFileWorkerEvent:
    """Route one provider-neutral File event to the matching application use case."""

    upload_completion_handler: UploadCompletionHandler
    malware_scan_handler: MalwareScanResultHandler

    async def handle(self, event: FileWorkerEvent) -> None:
        if isinstance(event, UploadCompletionEvent):
            await self.upload_completion_handler.handle(event)
            return
        await self.malware_scan_handler.handle(event)


__all__ = ["FileWorkerEvent", "HandleFileWorkerEvent"]
