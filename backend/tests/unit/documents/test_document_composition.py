import asyncio
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from nexus.composition.document_worker import build_document_worker_composition
from nexus.config.document_worker_settings import DocumentWorkerSettings
from nexus.dev.local_document_dispatcher import LocalDocumentDispatcherSettings


def settings(**kwargs):
    return DocumentWorkerSettings(
        database_url="postgresql://test:test@localhost/test",
        azure_service_bus_fully_qualified_namespace="nexus.servicebus.windows.net",
        **kwargs,
    )


def test_consumer_fails_before_resources():
    async def run():
        with (
            patch(
                "nexus.composition.document_worker.ManagedIdentityCredential"
            ) as credential,
            patch("nexus.composition.document_worker.build_database") as db,
        ):
            with pytest.raises(ValueError, match="real downstream processor"):
                await build_document_worker_composition(settings(), consume=True)
            credential.assert_not_called()
            db.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"document_dispatch_concurrency": 0},
        {"document_worker_concurrency": 21},
        {"document_dispatch_send_timeout_seconds": 60},
        {"document_processing_version": " padded "},
    ],
)
def test_settings_bounds(kwargs):
    with pytest.raises(ValidationError):
        settings(**kwargs)


@pytest.mark.parametrize(
    "environment", ["production", "staging", "development", "test"]
)
def test_local_auth_restricted(environment):
    kwargs = {
        "database_url": "postgresql://test:test@localhost/test",
        "azure_service_bus_connection_string": "private",
        "app_env": environment,
    }
    if environment in {"development", "test"}:
        assert LocalDocumentDispatcherSettings(**kwargs).app_env == environment
    else:
        with pytest.raises(ValidationError):
            LocalDocumentDispatcherSettings(**kwargs)


def test_dispatch_composition_uses_managed_identity_and_closes_resources():
    from unittest.mock import AsyncMock, MagicMock

    async def run():
        credential, client, database = AsyncMock(), MagicMock(), MagicMock()
        client.close = AsyncMock()
        database.dispose = AsyncMock()
        with (
            patch(
                "nexus.composition.document_worker.ManagedIdentityCredential",
                return_value=credential,
            ) as identity,
            patch(
                "nexus.composition.document_worker.ServiceBusClient",
                return_value=client,
            ) as servicebus,
            patch(
                "nexus.composition.document_worker.build_database",
                return_value=database,
            ) as db,
        ):
            composition = await build_document_worker_composition(settings())
            assert composition.worker is None
            identity.assert_called_once_with()
            assert servicebus.call_args.kwargs["credential"] is credential
            assert db.call_args.kwargs == {"pool_size": 2, "max_overflow": 0}
            client.get_queue_receiver.assert_not_called()
            await composition.close()
            client.close.assert_awaited_once()
            credential.close.assert_awaited_once()
            database.dispose.assert_awaited_once()

    asyncio.run(run())


def test_startup_failure_closes_resources():
    from unittest.mock import AsyncMock, MagicMock

    async def run():
        credential, client = AsyncMock(), MagicMock()
        client.close = AsyncMock()
        with (
            patch(
                "nexus.composition.document_worker.ManagedIdentityCredential",
                return_value=credential,
            ),
            patch(
                "nexus.composition.document_worker.ServiceBusClient",
                return_value=client,
            ),
            patch(
                "nexus.composition.document_worker.build_database",
                side_effect=RuntimeError(),
            ),
        ):
            with pytest.raises(RuntimeError):
                await build_document_worker_composition(settings())
            client.close.assert_awaited_once()
            credential.close.assert_awaited_once()

    asyncio.run(run())
