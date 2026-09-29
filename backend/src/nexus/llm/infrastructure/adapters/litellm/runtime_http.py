"""LiteLLM HTTP handler shim backed by a Nexus-owned pinned HTTPX client."""

from __future__ import annotations

from typing import Any

import httpx

from nexus.config.litellm import require_local_litellm_metadata

# This module is itself a supported LiteLLM import boundary.
require_local_litellm_metadata()

from litellm.llms.custom_httpx.http_handler import (
    AsyncHTTPHandler,
)


class PinnedLiteLLMAsyncHTTPHandler(AsyncHTTPHandler):
    """Borrow a secure client without LiteLLM retries or fallback clients.

    Anthropic and Gemini in LiteLLM 1.103.0 accept only an
    ``AsyncHTTPHandler`` instance. The base handler creates a new unpinned
    client after some connection failures, so Nexus overrides ``post`` and
    keeps ownership and cleanup with the request-scoped runtime transport.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.timeout = None
        self.event_hooks = None
        self.ssl_verify = None
        self.shared_session = None
        self._owns_client = False
        self._client = client
        self.client_alias = "nexus-pinned-runtime"

    async def post(
        self,
        url: str,
        data: Any = None,
        json: dict[str, object] | None = None,
        params: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        timeout: Any = None,
        stream: bool = False,
        logging_obj: Any = None,
        files: Any = None,
        content: Any = None,
    ) -> httpx.Response:
        del logging_obj
        request = self.client.build_request(
            "POST",
            url,
            data=data,
            json=json,
            params=params,
            headers=headers,
            timeout=timeout,
            files=files,
            content=content,
        )
        response = await self.client.send(request, stream=stream)
        response.raise_for_status()
        return response


__all__ = ["PinnedLiteLLMAsyncHTTPHandler"]
