"""Connection-string authentication confined to development/test dispatch."""

import asyncio
from contextlib import AsyncExitStack

from azure.servicebus.aio import ServiceBusClient
from pydantic import SecretStr, field_validator

from nexus.composition.document_worker import _compose
from nexus.config.document_worker_settings import DocumentWorkerSettings
from nexus.config.settings import ROOT_ENV_FILE
from nexus.logging import configure_logging, get_logger
from nexus.workers.document_processing import run_document_process


class LocalDocumentDispatcherSettings(DocumentWorkerSettings):
    app_env: str = "development"
    azure_service_bus_fully_qualified_namespace: str = "sbemulatorns"
    azure_service_bus_connection_string: SecretStr

    @field_validator("app_env")
    @classmethod
    def local_only(cls, value: str) -> str:
        if value not in {"development", "test"}:
            raise ValueError(
                "Local document dispatch is restricted to development/test"
            )
        return value


async def run() -> None:
    settings = LocalDocumentDispatcherSettings(_env_file=ROOT_ENV_FILE)  # type: ignore[call-arg]
    configure_logging(settings.log_level)
    resources = AsyncExitStack()
    try:
        client = ServiceBusClient.from_connection_string(
            settings.azure_service_bus_connection_string.get_secret_value()
        )
        resources.push_async_callback(client.close)
        composition = _compose(settings, client, resources)
    except BaseException:
        await resources.aclose()
        raise
    await run_document_process(composition)


def main() -> None:
    configure_logging()
    try:
        asyncio.run(run())
    except Exception as exc:  # noqa: BLE001 - sanitized CLI errors
        get_logger(__name__).error(
            "local_document_dispatch_failed", error_type=type(exc).__name__
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
