from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass

import pytest

from nexus.config.file_worker_settings import FileWorkerSettings
from nexus.files.ports import UploadCompletionEvent
from nexus.workers import file_upload_completion as entrypoint


class StubHandler:
    async def handle(self, event: UploadCompletionEvent) -> None:
        del event


class FakeWorker:
    def __init__(self) -> None:
        self.run_calls = 0
        self.stop_event: asyncio.Event | None = None

    async def run(self, stop_event: asyncio.Event) -> None:
        self.run_calls += 1
        self.stop_event = stop_event
        stop_event.set()


@dataclass
class FakeComposition:
    worker: FakeWorker
    close_calls: int = 0

    async def close(self) -> None:
        self.close_calls += 1


class FakeLoop:
    def __init__(self) -> None:
        self.handlers: dict[signal.Signals, object] = {}
        self.removed: list[signal.Signals] = []

    def add_signal_handler(
        self,
        handled_signal: signal.Signals,
        callback: object,
    ) -> None:
        self.handlers[handled_signal] = callback

    def remove_signal_handler(self, handled_signal: signal.Signals) -> bool:
        self.removed.append(handled_signal)
        return True


def _settings() -> FileWorkerSettings:
    return FileWorkerSettings(
        _env_file=None,
        azure_service_bus_fully_qualified_namespace=(
            "nexus.servicebus.windows.net"
        ),
        azure_service_bus_queue_name="file-upload-completions",
        azure_event_grid_expected_source="/subscriptions/source",
        azure_storage_container="nexus-files",
    )


def test_entrypoint_installs_signals_runs_and_closes_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        fake_loop = FakeLoop()
        composition = FakeComposition(FakeWorker())

        async def build(*_args: object, **_kwargs: object) -> FakeComposition:
            return composition

        monkeypatch.setattr(entrypoint.asyncio, "get_running_loop", lambda: fake_loop)
        monkeypatch.setattr(entrypoint, "build_file_worker_composition", build)

        await entrypoint.run_file_upload_completion_worker(
            _settings(),
            handler=StubHandler(),
        )

        assert set(fake_loop.handlers) == {signal.SIGTERM, signal.SIGINT}
        assert set(fake_loop.removed) == {signal.SIGTERM, signal.SIGINT}
        assert composition.worker.run_calls == 1
        assert composition.worker.stop_event is not None
        assert composition.worker.stop_event.is_set()
        assert composition.close_calls == 1

    asyncio.run(scenario())


def test_main_fails_closed_before_loading_settings_or_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_loaded = False

    def load_settings() -> FileWorkerSettings:
        nonlocal settings_loaded
        settings_loaded = True
        return _settings()

    monkeypatch.setattr(entrypoint, "load_file_worker_settings", load_settings)

    with pytest.raises(SystemExit) as caught:
        entrypoint.main()

    assert caught.value.code == 1
    assert settings_loaded is False
