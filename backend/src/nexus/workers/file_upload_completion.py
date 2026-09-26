"""Entrypoint for the dedicated File upload-completion worker."""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Coroutine
from typing import Any

from nexus.composition.file_worker import (
    build_file_worker_composition,
)
from nexus.config.file_worker_settings import (
    FileWorkerSettings,
    load_file_worker_settings,
)
from nexus.logging import configure_logging, get_logger

logger = get_logger(__name__)


async def run_file_upload_completion_worker(
    settings: FileWorkerSettings,
) -> None:
    """Run one worker until SIGTERM, SIGINT, or task cancellation."""

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    installed_signals: list[signal.Signals] = []
    for handled_signal in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(handled_signal, stop_event.set)
        except NotImplementedError:  # pragma: no cover - non-POSIX fallback
            continue
        installed_signals.append(handled_signal)

    composition = None
    try:
        composition = await build_file_worker_composition(settings)
        await composition.worker.run(stop_event)
    finally:
        for handled_signal in installed_signals:
            loop.remove_signal_handler(handled_signal)
        if composition is not None:
            await _settle_cleanup(composition.close())


def main() -> None:
    """Load configuration and run the dedicated process."""

    configure_logging()
    try:
        settings = load_file_worker_settings()
    except Exception as exc:  # noqa: BLE001 - CLI startup must fail closed
        logger.error(
            "file_upload_completion_worker_startup_failed",
            error_type=type(exc).__name__,
        )
        raise SystemExit(1) from None

    configure_logging(settings.log_level)
    try:
        asyncio.run(run_file_upload_completion_worker(settings))
    except Exception as exc:  # noqa: BLE001 - CLI runtime must fail closed
        logger.error(
            "file_upload_completion_worker_runtime_failed",
            error_type=type(exc).__name__,
        )
        raise SystemExit(1) from None


async def _settle_cleanup(operation: Coroutine[Any, Any, None]) -> None:
    cleanup = asyncio.create_task(operation)
    try:
        await asyncio.shield(cleanup)
    except asyncio.CancelledError:
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                continue
        raise


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    main()
