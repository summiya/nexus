from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass, field

import pytest

from nexus.infrastructure.model_providers.outbound_endpoint import (
    PinnedResolver,
    ResolvedAddress,
    SystemHostResolver,
    UnsafeProviderEndpointError,
    parse_https_endpoint,
    resolve_public_addresses,
)


@dataclass
class StubResolver:
    answers: tuple[ResolvedAddress, ...]
    calls: list[tuple[str, int]] = field(default_factory=list)

    async def resolve(self, *, host: str, port: int) -> tuple[ResolvedAddress, ...]:
        self.calls.append((host, port))
        return self.answers


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "0.0.0.0",
        "169.254.169.254",
        "100.64.0.1",
        "::1",
        "::ffff:127.0.0.1",
    ],
)
def test_non_global_addresses_are_rejected(address: str) -> None:
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    resolver = StubResolver((ResolvedAddress(address, family),))

    with pytest.raises(UnsafeProviderEndpointError):
        asyncio.run(
            resolve_public_addresses(
                parse_https_endpoint("https://provider.example/v1"),
                resolver=resolver,
            )
        )


def test_all_resolved_addresses_must_be_global() -> None:
    resolver = StubResolver(
        (
            ResolvedAddress("8.8.8.8", socket.AF_INET),
            ResolvedAddress("127.0.0.1", socket.AF_INET),
        )
    )

    with pytest.raises(UnsafeProviderEndpointError):
        asyncio.run(
            resolve_public_addresses(
                parse_https_endpoint("https://provider.example/v1"),
                resolver=resolver,
            )
        )


def test_checked_address_is_pinned_without_second_system_lookup() -> None:
    resolver = StubResolver((ResolvedAddress("8.8.8.8", socket.AF_INET),))
    parsed = parse_https_endpoint("https://provider.example/v1")
    approved = asyncio.run(resolve_public_addresses(parsed, resolver=resolver))
    pinned = PinnedResolver(hostname="provider.example", addresses=approved)

    first = asyncio.run(pinned.resolve("provider.example", 443))
    second = asyncio.run(pinned.resolve("provider.example", 443))

    assert resolver.calls == [("provider.example", 443)]
    assert [answer["host"] for answer in first] == ["8.8.8.8"]
    assert [answer["host"] for answer in second] == ["8.8.8.8"]
    assert all(answer["hostname"] == "provider.example" for answer in first)


def test_pinned_resolver_rejects_a_different_hostname() -> None:
    pinned = PinnedResolver(
        hostname="provider.example",
        addresses=(ResolvedAddress("8.8.8.8", socket.AF_INET),),
    )

    with pytest.raises(OSError, match="Unexpected provider hostname"):
        asyncio.run(pinned.resolve("other.example", 443))


@pytest.mark.parametrize(
    "host",
    ["127.1", "2130706433", "0x7f.0.0.1"],
)
def test_legacy_numeric_loopback_forms_are_resolved_then_rejected(host: str) -> None:
    with pytest.raises(UnsafeProviderEndpointError):
        asyncio.run(
            resolve_public_addresses(
                parse_https_endpoint(f"https://{host}/v1"),
                resolver=SystemHostResolver(),
            )
        )
