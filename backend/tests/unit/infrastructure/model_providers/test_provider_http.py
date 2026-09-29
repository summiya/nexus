from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass, field
from typing import Any, Self

import pytest

from nexus.infrastructure.model_providers import provider_http as module
from nexus.infrastructure.model_providers.outbound_endpoint import (
    PinnedResolver,
    ResolvedAddress,
)


@dataclass
class SequenceResolver:
    calls: int = 0

    async def resolve(self, *, host: str, port: int) -> tuple[ResolvedAddress, ...]:
        del host, port
        self.calls += 1
        if self.calls == 1:
            return (ResolvedAddress("8.8.8.8", socket.AF_INET),)
        return (ResolvedAddress("127.0.0.1", socket.AF_INET),)


@dataclass
class FakeResponse:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


@dataclass
class FakeSession:
    constructor_kwargs: dict[str, Any]
    request_kwargs: dict[str, Any] = field(default_factory=dict)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.request_kwargs = {"url": url, **kwargs}
        return FakeResponse()


def test_pinned_provider_get_uses_only_the_checked_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream = SequenceResolver()
    captured: dict[str, Any] = {}

    def connector_factory(**kwargs: object) -> object:
        captured["connector_kwargs"] = kwargs
        return object()

    def session_factory(**kwargs: object) -> FakeSession:
        session = FakeSession(dict(kwargs))
        captured["session"] = session
        return session

    monkeypatch.setattr(module.aiohttp, "TCPConnector", connector_factory)
    monkeypatch.setattr(module.aiohttp, "ClientSession", session_factory)

    async def exercise() -> list[object]:
        async with module.pinned_provider_get(
            url="https://provider.example/v1/models",
            headers={"Authorization": "Bearer redacted"},
            resolver=upstream,
            timeout_seconds=3,
        ):
            pinned = captured["connector_kwargs"]["resolver"]
            assert isinstance(pinned, PinnedResolver)
            return await pinned.resolve("provider.example", 443)

    answers = asyncio.run(exercise())

    assert upstream.calls == 1
    assert [answer["host"] for answer in answers] == ["8.8.8.8"]
    assert all(answer["hostname"] == "provider.example" for answer in answers)
    session = captured["session"]
    assert session.request_kwargs["url"] == "https://provider.example/v1/models"
    assert session.constructor_kwargs["trust_env"] is False
    assert session.request_kwargs["allow_redirects"] is False
