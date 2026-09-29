"""LiteLLM HTTP handler shim backed by a Nexus-owned pinned HTTPX client."""

from __future__ import annotations

from typing import Any

import httpx

from nexus.config.litellm import require_local_litellm_metadata
from nexus.llm.domain import (
    LLMInvalidRequestError,
    LLMProviderUnavailableError,
    LLMTimeoutError,
)

# This module is itself a supported LiteLLM import boundary.
require_local_litellm_metadata()

from litellm.exceptions import (
    APIConnectionError,
    BadRequestError,
    Timeout,
)
from litellm.llms.custom_httpx.http_handler import (
    AsyncHTTPHandler,
)

_SAFE_STATUS_MESSAGE = "LLM provider request failed."
_RUNTIME_MODEL = "nexus-runtime"
_RUNTIME_PROVIDER = "nexus-runtime"


class _SafeHTTPStatusError(httpx.HTTPStatusError):
    """Expose only the status shape expected by pinned LiteLLM handlers."""

    def __init__(
        self,
        *,
        status_code: int,
        request: httpx.Request,
        response: httpx.Response,
    ) -> None:
        super().__init__(
            _SAFE_STATUS_MESSAGE,
            request=request,
            response=response,
        )
        self.status_code = status_code


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
        params: dict[str, Any] | None = None,
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
        try:
            response = await self.client.send(request, stream=stream)
        except LLMTimeoutError:
            raise Timeout(
                message="LLM provider request timed out.",
                model=_RUNTIME_MODEL,
                llm_provider=_RUNTIME_PROVIDER,
                headers={},
            ) from None
        except LLMProviderUnavailableError:
            raise APIConnectionError(
                message="LLM provider is temporarily unavailable.",
                model=_RUNTIME_MODEL,
                llm_provider=_RUNTIME_PROVIDER,
            ) from None
        except LLMInvalidRequestError:
            raise BadRequestError(
                message="LLM provider endpoint is not supported.",
                model=_RUNTIME_MODEL,
                llm_provider=_RUNTIME_PROVIDER,
            ) from None

        if not response.is_success:
            await _raise_safe_http_status(response)
        return response


async def _raise_safe_http_status(response: httpx.Response) -> None:
    """Preserve status classification without exposing endpoint/body details."""

    status_code = response.status_code
    await response.aclose()
    safe_request = httpx.Request("POST", "https://provider.invalid/")
    safe_response = httpx.Response(
        status_code=status_code,
        request=safe_request,
        content=b"",
    )
    raise _SafeHTTPStatusError(
        status_code=status_code,
        request=safe_request,
        response=safe_response,
    )


__all__ = ["PinnedLiteLLMAsyncHTTPHandler"]
