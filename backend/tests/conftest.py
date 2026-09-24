from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus.config.settings import Settings
from nexus.files.ports import ObjectStorage
from nexus.infrastructure.mailer import EmailMessage
from nexus.main import create_app


class AllowAllRateLimiter:
    async def allow(self, *, key: str, limit: int, window_seconds: int) -> bool:
        del key, limit, window_seconds
        return True


class StubEmailProvider:
    def send(self, message: EmailMessage) -> None:
        del message


@pytest.fixture
def app_settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/15",
        cors_allowed_origins=["http://localhost:5173"],
        otp_hmac_secret="test-secret-value-with-enough-length",
        auth_token_secret="test-auth-token-secret-with-enough-length",
        refresh_token_secret="test-refresh-token-secret-with-enough-length",
    )


@pytest.fixture
def app(app_settings: Settings) -> FastAPI:
    return create_app(
        app_settings,
        rate_limiter=AllowAllRateLimiter(),
        email_provider=StubEmailProvider(),
        object_storage=Mock(spec=ObjectStorage),
    )


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
