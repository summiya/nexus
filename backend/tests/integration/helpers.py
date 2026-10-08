"""Shared File seed data and isolated Azurite infrastructure for integration tests."""

from __future__ import annotations

import os
import socket
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob.aio import ContainerClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from nexus.files.domain import File, FileStorageStatus
from nexus.infrastructure.persistence.models import File as FileModel
from nexus.infrastructure.persistence.models import Organization, User
from nexus.infrastructure.storage import AzureBlobObjectStorage

NOW = datetime(2026, 10, 5, tzinfo=UTC)

_DEFAULT_AZURITE_CONNECTION_STRING = (
    "DefaultEndpointsProtocol=http;"
    "AccountName=devstoreaccount1;"
    "AccountKey="
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/"
    "K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
)


def seed_file(
    engine: Engine, *, status: str = "pending", name: str = "report.pdf"
) -> File:
    with Session(engine) as session:
        org = Organization(
            public_id=uuid4(), name="Initiation", slug=uuid4().hex, status="active"
        )
        user = User(
            public_id=uuid4(),
            organization=org,
            email=f"{uuid4().hex}@example.com",
            status="active",
        )
        session.add(user)
        session.flush()
        model = FileModel(
            public_id=uuid4(),
            organization_id=org.id,
            created_by_user_id=user.id,
            original_name=name,
            mime_type="application/pdf",
            size_bytes=42,
            storage_key=f"files/{uuid4().hex}",
            storage_status=status,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(model)
        session.flush()
        file = File(
            public_id=model.public_id,
            organization_public_id=org.public_id,
            created_by_user_public_id=user.public_id,
            original_name=name,
            mime_type=model.mime_type,
            size_bytes=42,
            storage_key=model.storage_key,
            storage_status=FileStorageStatus(status),
            checksum_sha256=None,
            created_at=NOW,
            updated_at=NOW,
        )
        session.commit()
        return file


async def byte_stream(*chunks: bytes) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


def _azurite_connection_string() -> str:
    return os.environ.get(
        "NEXUS_TEST_AZURITE_CONNECTION_STRING",
        _DEFAULT_AZURITE_CONNECTION_STRING,
    )


def _azurite_endpoint(connection_string: str) -> tuple[str, int]:
    endpoint = next(
        value.split("=", 1)[1]
        for value in connection_string.split(";")
        if value.startswith("BlobEndpoint=")
    )
    parsed = urlparse(endpoint)
    if parsed.hostname is None:
        raise ValueError("Azurite BlobEndpoint must contain a hostname")
    return parsed.hostname, parsed.port or 10000


def _require_azurite(connection_string: str) -> None:
    host, port = _azurite_endpoint(connection_string)
    try:
        with socket.create_connection((host, port), timeout=0.5):
            pass
    except OSError as exc:
        if os.environ.get("NEXUS_REQUIRE_AZURITE_TESTS") == "true":
            pytest.fail(f"Azurite is required but unavailable at {host}:{port}: {exc}")
        pytest.skip("Azurite is not available for object storage integration tests")


async def with_isolated_storage(
    scenario: Callable[
        [AzureBlobObjectStorage, ContainerClient],
        Awaitable[None],
    ],
) -> None:
    connection_string = _azurite_connection_string()
    _require_azurite(connection_string)
    container_name = f"nexus-{uuid.uuid4().hex}"
    client = ContainerClient.from_connection_string(
        connection_string,
        container_name=container_name,
        max_single_get_size=4,
        max_chunk_get_size=4,
    )
    try:
        await client.create_container()
        await scenario(AzureBlobObjectStorage(client), client)
    finally:
        with suppress(ResourceNotFoundError):
            await client.delete_container()
        await client.close()
