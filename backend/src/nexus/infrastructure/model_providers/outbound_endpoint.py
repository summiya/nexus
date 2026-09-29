"""Resolve, validate, and pin outbound provider endpoints."""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Protocol
from urllib.parse import SplitResult, urlsplit

from aiohttp.abc import AbstractResolver, ResolveResult


class UnsafeProviderEndpointError(ValueError):
    """The outbound endpoint cannot be used under the public-network policy."""


@dataclass(frozen=True, slots=True)
class ResolvedAddress:
    host: str
    family: socket.AddressFamily


class HostResolver(Protocol):
    async def resolve(self, *, host: str, port: int) -> tuple[ResolvedAddress, ...]: ...


class SystemHostResolver:
    """Resolve one host through the running event loop."""

    async def resolve(self, *, host: str, port: int) -> tuple[ResolvedAddress, ...]:
        loop = asyncio.get_running_loop()
        results = await loop.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
        )
        addresses: dict[tuple[str, socket.AddressFamily], ResolvedAddress] = {}
        for family, _type, _proto, _canonname, sockaddr in results:
            if family not in (socket.AF_INET, socket.AF_INET6):
                continue
            resolved = ResolvedAddress(host=str(sockaddr[0]), family=family)
            addresses[(resolved.host, resolved.family)] = resolved
        return tuple(addresses.values())


def parse_https_endpoint(url: str) -> SplitResult:
    """Parse the endpoint required by the validation transport."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeProviderEndpointError(
            "Provider endpoint is not supported."
        ) from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise UnsafeProviderEndpointError("Provider endpoint is not supported.")
    if port is not None and not 1 <= port <= 65535:
        raise UnsafeProviderEndpointError("Provider endpoint is not supported.")
    return parsed


async def resolve_public_addresses(
    parsed: SplitResult,
    *,
    resolver: HostResolver,
) -> tuple[ResolvedAddress, ...]:
    """Resolve once and require every result to be globally routable."""
    host = parsed.hostname
    if host is None:  # guarded by parse_https_endpoint
        raise UnsafeProviderEndpointError("Provider endpoint is not supported.")
    addresses = await resolver.resolve(host=host, port=parsed.port or 443)
    if not addresses:
        raise OSError("Provider hostname did not resolve")
    for resolved in addresses:
        try:
            address: IPv4Address | IPv6Address = ip_address(resolved.host)
        except ValueError as exc:
            raise UnsafeProviderEndpointError(
                "Provider endpoint is not supported."
            ) from exc
        if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        if (
            not address.is_global
            or address.is_multicast
            or (isinstance(address, IPv6Address) and address.is_site_local)
        ):
            raise UnsafeProviderEndpointError("Provider endpoint is not supported.")
    return addresses


class PinnedResolver(AbstractResolver):
    """Return only addresses already approved for one original hostname."""

    def __init__(
        self,
        *,
        hostname: str,
        addresses: tuple[ResolvedAddress, ...],
    ) -> None:
        self._hostname = _normalized_hostname(hostname)
        self._addresses = addresses

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_UNSPEC,
    ) -> list[ResolveResult]:
        if _normalized_hostname(host) != self._hostname:
            raise OSError("Unexpected provider hostname")
        return [
            ResolveResult(
                hostname=host,
                host=address.host,
                port=port,
                family=address.family,
                proto=socket.IPPROTO_TCP,
                flags=0,
            )
            for address in self._addresses
            if family in (socket.AF_UNSPEC, address.family)
        ]

    async def close(self) -> None:
        return None


def _normalized_hostname(host: str) -> str:
    return host.rstrip(".").lower()


__all__ = [
    "HostResolver",
    "PinnedResolver",
    "ResolvedAddress",
    "SystemHostResolver",
    "UnsafeProviderEndpointError",
    "parse_https_endpoint",
    "resolve_public_addresses",
]
