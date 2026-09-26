from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass
from typing import Any
from unittest.mock import Mock

import pytest

from nexus.config.file_worker_settings import FileWorkerSettings
from nexus.workers import file_upload_completion as entrypoint

DEVELOPMENT_CONTEXT_KEY = "bmV4dXMtZGV2ZWxvcG1lbnQtdXBsb2FkLWtleS0wMDE"


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
        database_url="postgresql://nexus:nexus@postgres:5432/nexus",
        file_upload_context_key=DEVELOPMENT_CONTEXT_KEY,
        azure_service_bus_fully_qualified_namespace=("nexus.servicebus.windows.net"),
        azure_service_bus_queue_name="file-upload-completions",
        azure_event_grid_expected_source="/subscriptions/source",
        azure_storage_container="nexus-files",
        azure_storage_account_url="https://nexus.blob.core.windows.net",
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

        await entrypoint.run_file_upload_completion_worker(_settings())

        assert set(fake_loop.handlers) == {signal.SIGTERM, signal.SIGINT}
        assert set(fake_loop.removed) == {signal.SIGTERM, signal.SIGINT}
        assert composition.worker.run_calls == 1
        assert composition.worker.stop_event is not None
        assert composition.worker.stop_event.is_set()
        assert composition.close_calls == 1

    asyncio.run(scenario())


def test_main_fails_closed_when_settings_cannot_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    safe_logger = Mock()

    def load_settings() -> FileWorkerSettings:
        raise RuntimeError("sensitive configuration detail")

    run = Mock()
    monkeypatch.setattr(entrypoint, "load_file_worker_settings", load_settings)
    monkeypatch.setattr(entrypoint, "logger", safe_logger)
    monkeypatch.setattr(entrypoint.asyncio, "run", run)

    with pytest.raises(SystemExit) as caught:
        entrypoint.main()

    assert caught.value.code == 1
    run.assert_not_called()
    assert "sensitive configuration detail" not in repr(
        safe_logger.error.call_args_list
    )


def test_main_logs_only_runtime_error_type_and_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    safe_logger = Mock()

    def fail_run(operation: Any) -> None:
        operation.close()
        raise RuntimeError("sensitive provider response")

    monkeypatch.setattr(entrypoint, "load_file_worker_settings", _settings)
    monkeypatch.setattr(entrypoint, "configure_logging", Mock())
    monkeypatch.setattr(entrypoint, "logger", safe_logger)
    monkeypatch.setattr(entrypoint.asyncio, "run", fail_run)

    with pytest.raises(SystemExit) as caught:
        entrypoint.main()

    assert caught.value.code == 1
    safe_logger.error.assert_called_once_with(
        "file_upload_completion_worker_runtime_failed",
        error_type="RuntimeError",
    )
    assert "sensitive provider response" not in repr(safe_logger.error.call_args_list)
