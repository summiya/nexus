"""Shared pinned HTTP boundary for model-provider metadata requests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

import aiohttp

from nexus.infrastructure.model_providers.outbound_endpoint import (
    HostResolver,
    PinnedResolver,
    parse_https_endpoint,
    resolve_public_addresses,
)


@asynccontextmanager
async def pinned_provider_get(
    *,
    url: str,
    headers: Mapping[str, str],
    resolver: HostResolver,
    timeout_seconds: float,
) -> AsyncIterator[aiohttp.ClientResponse]:
    """GET through the checked address while retaining hostname TLS semantics."""

    parsed = parse_https_endpoint(url)
    addresses = await resolve_public_addresses(parsed, resolver=resolver)
    hostname = parsed.hostname
    if hostname is None:  # guarded by parse_https_endpoint
        raise RuntimeError("Parsed provider endpoint has no hostname")
    connector = aiohttp.TCPConnector(
        resolver=PinnedResolver(hostname=hostname, addresses=addresses),
        use_dns_cache=False,
        limit=1,
    )
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    async with (
        aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            trust_env=False,
            auto_decompress=False,
        ) as session,
        session.get(url, headers=headers, allow_redirects=False) as response,
    ):
        yield response


__all__ = ["pinned_provider_get"]
