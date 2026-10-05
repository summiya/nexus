import asyncio
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from nexus.composition.document_worker import build_document_worker_composition
from nexus.config.document_worker_settings import DocumentWorkerSettings
from nexus.dev import local_document_dispatcher
from nexus.dev.local_document_dispatcher import LocalDocumentDispatcherSettings
from nexus.infrastructure.messaging.azure_service_bus_document_processing import (
    AzureServiceBusDocumentPublisher,
)
from nexus.infrastructure.messaging.azure_service_bus_publisher import (
    AzureServiceBusQueuePublisher,
)


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
            patch(
                "nexus.composition.document_worker.AzureServiceBusQueuePublisher",
                wraps=AzureServiceBusQueuePublisher,
            ) as common,
            patch(
                "nexus.composition.document_worker.AzureServiceBusDocumentPublisher",
                wraps=AzureServiceBusDocumentPublisher,
            ) as document_publisher,
        ):
            composition = await build_document_worker_composition(settings())
            assert composition.worker is None
            identity.assert_called_once_with()
            assert servicebus.call_args.kwargs["credential"] is credential
            assert db.call_args.kwargs == {"pool_size": 2, "max_overflow": 0}
            client.get_queue_receiver.assert_not_called()
            common.assert_called_once_with(client)
            document_publisher.assert_called_once()
            assert isinstance(
                document_publisher.call_args.args[0], AzureServiceBusQueuePublisher
            )
            assert (
                document_publisher.call_args.args[1] == "document-processing-requests"
            )
            client.close.assert_not_called()
            await composition.close()
            client.close.assert_awaited_once()
            credential.close.assert_awaited_once()
            database.dispose.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize("environment", ["development", "test"])
def test_local_dispatcher_reuses_shared_composition_and_owned_client(environment):
    from unittest.mock import AsyncMock, MagicMock

    async def run():
        local_settings = LocalDocumentDispatcherSettings(
            database_url="postgresql://test:test@localhost/test",
            azure_service_bus_connection_string="local-test-only",
            app_env=environment,
        )
        client, database = MagicMock(), MagicMock()
        client.close = AsyncMock()
        database.dispose = AsyncMock()

        async def finish(composition):
            assert composition.worker is None
            client.close.assert_not_called()
            await composition.close()

        with (
            patch(
                "nexus.dev.local_document_dispatcher.LocalDocumentDispatcherSettings",
                return_value=local_settings,
            ),
            patch("nexus.dev.local_document_dispatcher.configure_logging"),
            patch("nexus.dev.local_document_dispatcher.ServiceBusClient") as servicebus,
            patch(
                "nexus.dev.local_document_dispatcher._compose",
                wraps=local_document_dispatcher._compose,
            ) as compose,
            patch(
                "nexus.dev.local_document_dispatcher.run_document_process",
                new=AsyncMock(side_effect=finish),
            ),
            patch(
                "nexus.composition.document_worker.build_database",
                return_value=database,
            ),
            patch(
                "nexus.composition.document_worker.AzureServiceBusQueuePublisher",
                wraps=AzureServiceBusQueuePublisher,
            ) as common,
            patch(
                "nexus.composition.document_worker.AzureServiceBusDocumentPublisher",
                wraps=AzureServiceBusDocumentPublisher,
            ) as document_publisher,
        ):
            servicebus.from_connection_string.return_value = client
            await local_document_dispatcher.run()
            servicebus.from_connection_string.assert_called_once_with("local-test-only")
            compose.assert_called_once()
            assert compose.call_args.args[:2] == (local_settings, client)
            common.assert_called_once_with(client)
            document_publisher.assert_called_once()
            assert isinstance(
                document_publisher.call_args.args[0], AzureServiceBusQueuePublisher
            )
            assert (
                document_publisher.call_args.args[1]
                == local_settings.azure_service_bus_document_queue_name
            )
            client.get_queue_receiver.assert_not_called()
            client.close.assert_awaited_once()
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
