"""Run dispatch by default; the real consumer requires explicit activation."""

import asyncio
import signal

from nexus.composition.document_worker import (
    DocumentWorkerComposition,
    build_document_worker_composition,
)
from nexus.config.document_worker_settings import DocumentWorkerSettings
from nexus.config.settings import ROOT_ENV_FILE
from nexus.logging import configure_logging, get_logger

logger = get_logger(__name__)


async def run_document_process(composition: DocumentWorkerComposition) -> None:
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    installed = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
            installed.append(sig)
        except NotImplementedError:  # pragma: no cover - POSIX deployment
            pass
    try:
        if composition.worker is None:
            await composition.dispatcher.run(stop)
        else:
            await composition.worker.run(stop)
    finally:
        for sig in installed:
            loop.remove_signal_handler(sig)
        cleanup = asyncio.create_task(composition.close())
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    continue
            cleanup.result()
            raise


async def _run(*, consume: bool = False) -> None:
    settings = DocumentWorkerSettings(_env_file=ROOT_ENV_FILE)  # type: ignore[call-arg]
    configure_logging(settings.log_level)
    composition = await build_document_worker_composition(settings, consume=consume)
    await run_document_process(composition)


def main(*, consume: bool = False) -> None:
    configure_logging()
    try:
        asyncio.run(_run(consume=consume))
    except Exception as exc:  # noqa: BLE001 - CLI startup/runtime fails closed
        logger.error("document_process_failed", error_type=type(exc).__name__)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
