"""One OpenAI embedding POST using Nexus-owned pinned HTTPX transport."""

from __future__ import annotations

import asyncio
import json
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from typing import Never, cast

import httpx

from nexus.infrastructure.model_providers.outbound_endpoint import (
    HostResolver,
    SystemHostResolver,
)
from nexus.infrastructure.model_providers.runtime_http import (
    RuntimeDeadline,
    SecureRuntimeHTTPClient,
    create_secure_runtime_http_client,
)
from nexus.llm.domain import (
    EmbeddingRequest,
    EmbeddingResult,
    LLMAuthenticationError,
    LLMError,
    LLMInvalidRequestError,
    LLMProviderUnavailableError,
    LLMRateLimitedError,
    LLMTimeoutError,
    LLMUnknownProviderError,
)
from nexus.llm.infrastructure.adapters._embedding_tokenizer import (
    load_embedding_tokenizer,
)
from nexus.model_providers.domain import (
    OpenAISettings,
    ProviderType,
    ResolvedEmbeddingModel,
)
from nexus.model_providers.ports import EmbeddingGateway

_ENDPOINT = "https://api.openai.com/v1/embeddings"
_MAX_INPUT_TOKENS = 8192
_MAX_BATCH_TOKENS = 300_000
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_INVALID_REQUEST = "Embedding request or target is not supported."
_INVALID_RESPONSE = "Embedding provider returned an invalid response."
_UNAVAILABLE = "Embedding provider is temporarily unavailable."
_TIMEOUT = "Embedding provider request timed out."


@dataclass(frozen=True)
class OpenAIEmbeddingAdapter(EmbeddingGateway):
    timeout_seconds: float
    resolver: HostResolver = field(default_factory=SystemHostResolver, repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.timeout_seconds) not in (int, float)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("Embedding timeout must be finite and positive")

    async def embed(
        self, *, request: EmbeddingRequest, target: ResolvedEmbeddingModel
    ) -> EmbeddingResult:
        deadline = RuntimeDeadline.start(self.timeout_seconds)
        http: SecureRuntimeHTTPClient | None = None
        response: httpx.Response | None = None
        try:
            _require_target(request, target)
            body = await _run_cpu(deadline, partial(_prepare_body, request, target))
            http = await create_secure_runtime_http_client(
                endpoint=_ENDPOINT,
                resolver=self.resolver,
                timeout_seconds=self.timeout_seconds,
                deadline=deadline,
            )
            deadline.remaining_seconds()
            outgoing = http.client.build_request(
                "POST",
                _ENDPOINT,
                content=body,
                headers={
                    "Authorization": f"Bearer {target.credential.reveal()}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                },
            )
            response = await deadline.run(http.client.send(outgoing, stream=True))
            if response.status_code != 200:
                raise _status_error(response.status_code)
            content = await deadline.run(_read_response(response))
            result = await _run_cpu(
                deadline, partial(_decode_response, content, request, target)
            )
        except asyncio.CancelledError:
            raise
        except LLMError:
            raise
        except httpx.TimeoutException:
            raise LLMTimeoutError(_TIMEOUT) from None
        except (httpx.TransportError, OSError):
            raise LLMProviderUnavailableError(_UNAVAILABLE) from None
        except (ValueError, UnicodeError):
            # HTTPX can reject malformed credential header bytes. Never expose them.
            raise LLMInvalidRequestError(_INVALID_REQUEST) from None
        finally:
            active_error = sys.exception() is not None
            cleanup = asyncio.create_task(_close_resources(response, http))
            await _settle(cleanup, deadline, suppress_errors=active_error)
        return result


def _require_target(request: EmbeddingRequest, target: ResolvedEmbeddingModel) -> None:
    if (
        not isinstance(request, EmbeddingRequest)
        or not isinstance(target, ResolvedEmbeddingModel)
        or target.provider_type is not ProviderType.OPENAI
        or not isinstance(target.settings, OpenAISettings)
    ):
        raise LLMInvalidRequestError(_INVALID_REQUEST)
    if target.provider_model_name == "text-embedding-3-small":
        maximum = 1536
    elif target.provider_model_name == "text-embedding-3-large":
        maximum = 3072
    else:
        raise LLMInvalidRequestError(_INVALID_REQUEST)
    if (
        type(target.embedding_dimension) is not int
        or not 1 <= target.embedding_dimension <= maximum
    ):
        raise LLMInvalidRequestError(_INVALID_REQUEST)


def _prepare_body(request: EmbeddingRequest, target: ResolvedEmbeddingModel) -> bytes:
    try:
        request = EmbeddingRequest(request.texts)
    except (TypeError, ValueError):
        raise LLMInvalidRequestError(_INVALID_REQUEST) from None
    encoding = load_embedding_tokenizer()
    total = 0
    for text in request.texts:
        count = len(encoding.encode_ordinary(text))
        total += count
        if not 1 <= count <= _MAX_INPUT_TOKENS or total > _MAX_BATCH_TOKENS:
            raise LLMInvalidRequestError(_INVALID_REQUEST)
    return json.dumps(
        {
            "model": target.provider_model_name,
            "input": request.texts,
            "dimensions": target.embedding_dimension,
            "encoding_format": "float",
        },
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


async def _read_response(response: httpx.Response) -> bytes:
    if (
        response.headers.get("content-encoding", "identity").strip().lower()
        != "identity"
        or response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise LLMUnknownProviderError(_INVALID_RESPONSE)
    declared = response.headers.get("content-length")
    size: int | None = None
    if declared is not None:
        if len(declared) > 20 or not declared.isascii() or not declared.isdecimal():
            raise LLMUnknownProviderError(_INVALID_RESPONSE)
        size = int(declared)
        if size > _MAX_RESPONSE_BYTES:
            raise LLMUnknownProviderError(_INVALID_RESPONSE)
    content = bytearray()
    async for chunk in response.aiter_raw():
        if len(content) + len(chunk) > _MAX_RESPONSE_BYTES:
            raise LLMUnknownProviderError(_INVALID_RESPONSE)
        content.extend(chunk)
    if size is not None and len(content) != size:
        raise LLMUnknownProviderError(_INVALID_RESPONSE)
    return bytes(content)


def _decode_response(
    content: bytes, request: EmbeddingRequest, target: ResolvedEmbeddingModel
) -> EmbeddingResult:
    try:
        payload: object = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        if not isinstance(payload, dict):
            raise TypeError("Invalid response object")
        if (
            payload.get("object") != "list"
            or payload.get("model") != target.provider_model_name
        ):
            raise ValueError("Invalid response identity")
        rows = payload.get("data")
        if not isinstance(rows, list) or len(rows) != len(request.texts):
            raise ValueError("Invalid output count")
        ordered: list[tuple[float, ...] | None] = [None] * len(request.texts)
        for row in rows:
            if not isinstance(row, dict) or row.get("object") != "embedding":
                raise ValueError("Invalid embedding object")
            index = row.get("index")
            if (
                type(index) is not int
                or not 0 <= index < len(ordered)
                or ordered[index] is not None
            ):
                raise ValueError("Invalid embedding index")
            vector = row.get("embedding")
            if (
                not isinstance(vector, list)
                or len(vector) != target.embedding_dimension
            ):
                raise ValueError("Invalid vector dimension")
            if any(type(value) not in (int, float) for value in vector):
                raise ValueError("Invalid vector value")
            ordered[index] = tuple(float(value) for value in vector)
        if any(vector is None for vector in ordered):
            raise ValueError("Incomplete embedding indexes")
        result = EmbeddingResult(cast(tuple[tuple[float, ...], ...], tuple(ordered)))
        result.validate_for(
            request=request, expected_dimension=target.embedding_dimension
        )
        return result
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise LLMUnknownProviderError(_INVALID_RESPONSE) from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _reject_constant(_value: str) -> Never:
    raise ValueError("Invalid JSON number")


def _status_error(status: int) -> LLMError:
    message = "Embedding provider request failed."
    if status in (401, 403):
        return LLMAuthenticationError(message)
    if status == 429:
        return LLMRateLimitedError(message)
    if status == 408:
        return LLMTimeoutError(_TIMEOUT)
    if status in (409, 425) or 500 <= status < 600:
        return LLMProviderUnavailableError(_UNAVAILABLE)
    if 400 <= status < 500:
        return LLMInvalidRequestError(message)
    return LLMUnknownProviderError(message)


async def _run_cpu[T](deadline: RuntimeDeadline, operation: Callable[[], T]) -> T:
    deadline.remaining_seconds()
    work = asyncio.create_task(asyncio.to_thread(operation))
    try:
        value = await deadline.run(asyncio.shield(work))
        deadline.remaining_seconds()
        return value
    finally:
        await _settle(work, deadline, suppress_errors=sys.exception() is not None)


async def _close_resources(
    response: httpx.Response | None, http: SecureRuntimeHTTPClient | None
) -> None:
    try:
        if response is not None:
            await response.aclose()
    finally:
        if http is not None:
            await http.aclose()


async def _settle[T](
    task: asyncio.Task[T], deadline: RuntimeDeadline, *, suppress_errors: bool
) -> None:
    """Use the invocation budget, then settle owned work before propagating failure."""
    cancellation: asyncio.CancelledError | None = None
    timeout: LLMTimeoutError | None = None
    while not task.done():
        try:
            if timeout is None:
                await deadline.run(asyncio.shield(task))
            else:
                # Expiry forbids success, but does not permit detached cleanup/threads.
                await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            cancellation = exc
        except LLMTimeoutError as exc:
            timeout = exc
        except Exception:  # noqa: BLE001 - task.result below preserves/maps the error
            break
    if cancellation is not None:
        if not task.cancelled():
            task.exception()
        raise cancellation
    if suppress_errors:
        if not task.cancelled():
            task.exception()
        return
    try:
        task.result()
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - sanitize owned-resource cleanup errors
        raise LLMProviderUnavailableError(_UNAVAILABLE) from None
    if timeout is not None:
        raise timeout
    deadline.remaining_seconds()
