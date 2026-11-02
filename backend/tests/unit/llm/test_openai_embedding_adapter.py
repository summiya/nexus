from __future__ import annotations

import ast
import asyncio
import json
import threading
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import httpx
import pytest

import nexus.llm.infrastructure.adapters.openai_embedding as module
from nexus.infrastructure.model_providers.outbound_endpoint import ResolvedAddress
from nexus.infrastructure.model_providers.runtime_http import (
    RuntimeDeadline,
    SecureRuntimeHTTPClient,
    create_secure_runtime_http_client,
)
from nexus.llm.domain import (
    EmbeddingRequest,
    EmbeddingResult,
    LLMAuthenticationError,
    LLMInvalidRequestError,
    LLMProviderUnavailableError,
    LLMRateLimitedError,
    LLMTimeoutError,
    LLMUnknownProviderError,
)
from nexus.llm.infrastructure.adapters.openai_embedding import OpenAIEmbeddingAdapter
from nexus.model_providers.domain import (
    ConfiguredModelId,
    GeminiSettings,
    OpenAISettings,
    OrganizationProviderId,
    ProviderCredentialSecret,
    ProviderType,
    ResolvedEmbeddingModel,
)

SECRET = "sentinel-private-embedding-key"
ENDPOINT = "https://api.openai.com/v1/embeddings"


def target(*, model="text-embedding-3-small", dimension=2, secret=SECRET):
    return ResolvedEmbeddingModel(
        model_id=ConfiguredModelId(UUID(int=1)),
        provider_id=OrganizationProviderId(UUID(int=2)),
        provider_type=ProviderType.OPENAI,
        provider_model_name=model,
        embedding_dimension=dimension,
        settings=OpenAISettings(),
        credential=ProviderCredentialSecret(secret),
    )


def response_body(*, model="text-embedding-3-small", count=2, dimension=2):
    return {
        "object": "list",
        "model": model,
        "data": [
            {"object": "embedding", "index": i, "embedding": [i + 0.5] * dimension}
            for i in range(count)
        ],
    }


class FakeEncoding:
    def __init__(self):
        self.counts = {}
        self.texts = []

    def encode_ordinary(self, text):
        self.texts.append(text)
        return range(self.counts.get(text, len(text)))


class TrackingStream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False
        self.pulls = 0

    async def __aiter__(self):
        for chunk in self.chunks:
            self.pulls += 1
            yield chunk

    async def aclose(self):
        self.closed = True


class Factory:
    def __init__(self):
        self.body = json.dumps(response_body()).encode()
        self.status = 200
        self.headers = {"content-type": "application/json"}
        self.error = None
        self.stream = None
        self.calls = []
        self.resources = []
        self.deadlines = []

    async def __call__(self, *, endpoint, resolver, timeout_seconds, deadline):
        assert endpoint == ENDPOINT
        assert deadline is not None
        self.deadlines.append(deadline)
        if self.stream is None:
            self.stream = TrackingStream((self.body,))

        async def respond(request):
            self.calls.append(request)
            if self.error is not None:
                raise self.error
            return httpx.Response(self.status, headers=self.headers, stream=self.stream)

        http = SecureRuntimeHTTPClient(
            httpx.AsyncClient(
                transport=httpx.MockTransport(respond),
                trust_env=False,
                follow_redirects=False,
                timeout=None,
            ),
            deadline,
        )
        self.resources.append(http)
        return http


@pytest.fixture
def setup(monkeypatch):
    encoding, factory = FakeEncoding(), Factory()
    monkeypatch.setattr(module, "load_embedding_tokenizer", lambda: encoding)
    monkeypatch.setattr(module, "create_secure_runtime_http_client", factory)
    return OpenAIEmbeddingAdapter(timeout_seconds=10), factory, encoding


def invoke(adapter, *, request=None, resolved=None):
    return asyncio.run(
        adapter.embed(
            request=EmbeddingRequest(("first", "second"))
            if request is None
            else request,
            target=target() if resolved is None else resolved,
        )
    )


@pytest.mark.parametrize(
    "model,maximum",
    [("text-embedding-3-small", 1536), ("text-embedding-3-large", 3072)],
)
def test_supported_models_send_authoritative_target_and_preserve_input(
    setup, model, maximum
):
    adapter, factory, encoding = setup
    factory.body = json.dumps(response_body(model=model, dimension=maximum)).encode()
    request = EmbeddingRequest((" first <|endoftext|> ", "日本語\nsecond"))
    result = invoke(
        adapter, request=request, resolved=target(model=model, dimension=maximum)
    )
    outgoing = factory.calls[0]
    assert str(outgoing.url) == ENDPOINT
    assert outgoing.method == "POST"
    assert outgoing.headers["authorization"] == f"Bearer {SECRET}"
    assert outgoing.headers["accept-encoding"] == "identity"
    assert json.loads(outgoing.content) == {
        "model": model,
        "input": list(request.texts),
        "dimensions": maximum,
        "encoding_format": "float",
    }
    assert encoding.texts == list(request.texts)
    assert result.dimension == maximum
    assert factory.resources[0].client.is_closed
    assert factory.stream.closed
    assert SECRET not in repr(adapter) + repr(result)


def test_response_indexes_restore_order_and_valid_json_integers_become_floats(setup):
    adapter, factory, _ = setup
    payload = response_body()
    payload["data"][0]["embedding"] = [1, -2]
    payload["data"].reverse()
    factory.body = json.dumps(payload).encode()
    result = invoke(adapter)
    assert result.vectors == ((1.0, -2.0), (1.5, 1.5))
    assert all(type(value) is float for vector in result.vectors for value in vector)


@pytest.mark.parametrize("count", [1, 128])
def test_batch_boundaries_produce_one_post_without_orchestration(setup, count):
    adapter, factory, _ = setup
    factory.body = json.dumps(response_body(count=count)).encode()
    result = invoke(adapter, request=EmbeddingRequest(("x",) * count))
    assert len(result.vectors) == count
    assert len(factory.calls) == 1


@pytest.mark.parametrize("dimension", [1, 1536])
def test_small_model_accepts_dimension_boundaries(setup, dimension):
    adapter, factory, _ = setup
    factory.body = json.dumps(response_body(dimension=dimension)).encode()
    assert invoke(adapter, resolved=target(dimension=dimension)).dimension == dimension


@pytest.mark.parametrize(
    "resolved",
    [
        target(model="unknown-model"),
        target(dimension=1537),
        target(model="text-embedding-3-large", dimension=3073),
        replace(target(), provider_type=ProviderType.GEMINI, settings=GeminiSettings()),
        replace(target(), settings=GeminiSettings()),
        None,
    ],
)
def test_invalid_targets_fail_before_tokenization_credentials_or_http(
    setup, monkeypatch, resolved
):
    adapter, factory, encoding = setup
    monkeypatch.setattr(
        ProviderCredentialSecret,
        "reveal",
        lambda _self: pytest.fail("Credential must stay protected"),
    )
    with pytest.raises(LLMInvalidRequestError):
        asyncio.run(adapter.embed(request=EmbeddingRequest(("text",)), target=resolved))
    assert factory.resources == encoding.texts == []


def test_wrong_request_type_is_rejected_without_io(setup):
    adapter, factory, _ = setup
    with pytest.raises(LLMInvalidRequestError):
        asyncio.run(adapter.embed(request=("text",), target=target()))
    assert factory.resources == []


@pytest.mark.parametrize(
    "texts", [(), ("x",) * 129, ("x" * (1024 * 1024 + 1),), (" \n",), (None,)]
)
def test_gateway_reuses_domain_input_validation_before_tokenizer_or_network(
    setup, texts
):
    adapter, factory, encoding = setup
    forged = object.__new__(EmbeddingRequest)
    object.__setattr__(forged, "texts", texts)
    with pytest.raises(LLMInvalidRequestError):
        invoke(adapter, request=forged)
    assert factory.resources == encoding.texts == []


@pytest.mark.parametrize("count,accepted", [(8192, True), (8193, False), (0, False)])
def test_per_input_token_limit_is_enforced(setup, count, accepted):
    adapter, factory, encoding = setup
    encoding.counts["first"] = count
    if accepted:
        invoke(adapter)
    else:
        with pytest.raises(LLMInvalidRequestError):
            invoke(adapter)
        assert factory.resources == []


@pytest.mark.parametrize("last,accepted", [(5088, True), (5089, False)])
def test_total_token_limit_is_enforced_without_splitting(setup, last, accepted):
    adapter, factory, encoding = setup
    texts = tuple(str(i) for i in range(37))
    encoding.counts = dict.fromkeys(texts, 8192)
    encoding.counts[texts[-1]] = last
    factory.body = json.dumps(response_body(count=37)).encode()
    if accepted:
        assert len(invoke(adapter, request=EmbeddingRequest(texts)).vectors) == 37
        assert len(factory.calls) == 1
    else:
        with pytest.raises(LLMInvalidRequestError):
            invoke(adapter, request=EmbeddingRequest(texts))
        assert factory.resources == []


@pytest.mark.parametrize(
    "status,error",
    [
        (400, LLMInvalidRequestError),
        (401, LLMAuthenticationError),
        (403, LLMAuthenticationError),
        (404, LLMInvalidRequestError),
        (408, LLMTimeoutError),
        (409, LLMProviderUnavailableError),
        (413, LLMInvalidRequestError),
        (422, LLMInvalidRequestError),
        (425, LLMProviderUnavailableError),
        (429, LLMRateLimitedError),
        (500, LLMProviderUnavailableError),
        (503, LLMProviderUnavailableError),
        (302, LLMUnknownProviderError),
        (204, LLMUnknownProviderError),
    ],
)
def test_status_errors_are_safe_do_not_read_bodies_or_retry(setup, status, error):
    adapter, factory, _ = setup
    factory.status = status
    factory.body = f"private provider error {SECRET}".encode()
    with pytest.raises(error) as raised:
        invoke(adapter)
    assert SECRET not in str(raised.value)
    assert "private provider error" not in str(raised.value)
    assert len(factory.calls) == 1
    assert factory.stream.pulls == 0
    assert factory.stream.closed and factory.resources[0].client.is_closed


@pytest.mark.parametrize(
    "error,expected",
    [
        (httpx.ReadTimeout("unsafe private detail"), LLMTimeoutError),
        (httpx.ConnectError("unsafe private detail"), LLMProviderUnavailableError),
        (OSError("unsafe private detail"), LLMProviderUnavailableError),
    ],
)
def test_transport_errors_are_safe_and_resources_close(setup, error, expected):
    adapter, factory, _ = setup
    factory.error = error
    with pytest.raises(expected) as raised:
        invoke(adapter)
    assert "unsafe" not in str(raised.value)
    assert factory.resources[0].client.is_closed
    assert len(factory.calls) == 1


@pytest.mark.parametrize(
    "damage",
    [
        "outer-type",
        "identity",
        "model",
        "rows-type",
        "missing",
        "excess",
        "row-type",
        "row-identity",
        "missing-index",
        "bool-index",
        "float-index",
        "negative-index",
        "high-index",
        "duplicate-index",
        "vector-type",
        "dimension",
        "bool",
        "string",
        "null",
        "nan",
        "infinity",
        "overflow",
    ],
)
def test_provider_response_integrity_errors_are_safe(setup, damage):
    adapter, factory, _ = setup
    payload = response_body()
    row = payload["data"][1]
    if damage == "outer-type":
        payload = []
    elif damage == "identity":
        payload["object"] = "wrong"
    elif damage == "model":
        payload["model"] = "different-model"
    elif damage == "rows-type":
        payload["data"] = {}
    elif damage == "missing":
        payload["data"].pop()
    elif damage == "excess":
        payload["data"].append(row)
    elif damage == "row-type":
        payload["data"][1] = None
    elif damage == "row-identity":
        row["object"] = "wrong"
    elif damage == "missing-index":
        row.pop("index")
    elif damage == "bool-index":
        row["index"] = True
    elif damage == "float-index":
        row["index"] = 1.0
    elif damage == "negative-index":
        row["index"] = -1
    elif damage == "high-index":
        row["index"] = 2
    elif damage == "duplicate-index":
        row["index"] = 0
    elif damage == "vector-type":
        row["embedding"] = "private-vector"
    elif damage == "dimension":
        row["embedding"] = [0.1]
    else:
        row["embedding"][0] = {
            "bool": True,
            "string": "private value",
            "null": None,
            "nan": float("nan"),
            "infinity": float("inf"),
            "overflow": 10**400,
        }[damage]
    factory.body = json.dumps(payload).encode()
    with pytest.raises(LLMUnknownProviderError) as captured:
        invoke(adapter)
    assert "private" not in str(captured.value)
    assert factory.resources[0].client.is_closed and factory.stream.closed


@pytest.mark.parametrize(
    "body",
    [
        b"private invalid JSON",
        b"\xff",
        b'{"object":"list","object":"list"}',
        b"[" * 1500,
    ],
)
def test_invalid_utf8_json_duplicates_and_depth_fail_safely(setup, body):
    adapter, factory, _ = setup
    factory.body = body
    with pytest.raises(LLMUnknownProviderError) as raised:
        invoke(adapter)
    assert "private" not in str(raised.value)


@pytest.mark.parametrize(
    "headers",
    [
        {"content-encoding": "gzip"},
        {"content-encoding": "br"},
        {"content-type": "text/html"},
        {"content-length": "-1"},
        {"content-length": "invalid"},
        {"content-length": "9" * 21},
        {"content-length": str(16 * 1024 * 1024 + 1)},
    ],
)
def test_invalid_encoding_type_or_declared_size_rejects_before_read(setup, headers):
    adapter, factory, _ = setup
    factory.headers.update(headers)
    with pytest.raises(LLMUnknownProviderError):
        invoke(adapter)
    assert factory.stream.pulls == 0
    assert factory.stream.closed


def test_response_limit_checks_actual_streamed_bytes_without_length_header(setup):
    adapter, factory, _ = setup
    factory.stream = TrackingStream((b"x" * (1024 * 1024),) * 17)
    with pytest.raises(LLMUnknownProviderError):
        invoke(adapter)
    assert factory.stream.pulls == 17
    assert factory.stream.closed


def test_length_header_cannot_bypass_actual_byte_limit(setup, monkeypatch):
    adapter, factory, _ = setup
    monkeypatch.setattr(module, "_MAX_RESPONSE_BYTES", 16)
    factory.headers["content-length"] = "1"
    factory.stream = TrackingStream((b"x" * 8, b"x" * 9, b"private unread tail"))
    with pytest.raises(LLMUnknownProviderError):
        invoke(adapter)
    assert factory.stream.pulls == 2
    assert factory.stream.closed


def test_exact_response_limit_and_length_are_accepted(setup, monkeypatch):
    adapter, factory, _ = setup
    monkeypatch.setattr(module, "_MAX_RESPONSE_BYTES", len(factory.body))
    factory.headers["content-length"] = str(len(factory.body))
    assert isinstance(invoke(adapter), EmbeddingResult)


def test_inaccurate_length_is_rejected_even_below_the_cap(setup):
    adapter, factory, _ = setup
    factory.headers["content-length"] = "1"
    with pytest.raises(LLMUnknownProviderError):
        invoke(adapter)


def test_missing_content_type_is_rejected(setup):
    adapter, factory, _ = setup
    factory.headers.clear()
    with pytest.raises(LLMUnknownProviderError):
        invoke(adapter)


def controlled_deadline(monkeypatch):
    now = [0.0]
    deadline = RuntimeDeadline.start(10, clock=lambda: now[0])
    monkeypatch.setattr(
        RuntimeDeadline, "start", classmethod(lambda cls, timeout_seconds: deadline)
    )
    return now, deadline


@pytest.mark.parametrize("stage", ["tokenization", "dns", "validation", "cleanup"])
def test_one_deadline_covers_all_processing_and_cleanup_without_late_success(
    setup, monkeypatch, stage
):
    adapter, factory, encoding = setup
    now, deadline = controlled_deadline(monkeypatch)
    if stage == "tokenization":

        def expire(_text):
            now[0] = 11
            return range(1)

        monkeypatch.setattr(encoding, "encode_ordinary", expire)
    elif stage == "dns":

        async def expire_factory(**kwargs):
            resource = await factory(**kwargs)
            now[0] = 11
            return resource

        monkeypatch.setattr(module, "create_secure_runtime_http_client", expire_factory)
    elif stage == "validation":
        original = module._decode_response

        def expire(*args):
            result = original(*args)
            now[0] = 11
            return result

        monkeypatch.setattr(module, "_decode_response", expire)
    else:
        original = factory.__call__

        async def with_expiring_close(**kwargs):
            resource = await original(**kwargs)
            close = resource.client.aclose

            async def expire():
                await close()
                now[0] = 11

            monkeypatch.setattr(resource.client, "aclose", expire)
            return resource

        monkeypatch.setattr(
            module, "create_secure_runtime_http_client", with_expiring_close
        )
    with pytest.raises(LLMTimeoutError):
        invoke(adapter)
    assert all(value is deadline for value in factory.deadlines)
    assert all(resource.client.is_closed for resource in factory.resources)
    if stage in {"tokenization", "dns"}:
        assert factory.calls == []


@pytest.mark.parametrize("stage", ["headers", "body"])
def test_real_deadline_interrupts_blocked_http_stages_and_closes(setup, stage):
    _, factory, _ = setup
    # Leave room for thread startup before exercising a deliberately blocked HTTP stage.
    adapter = OpenAIEmbeddingAdapter(timeout_seconds=1)
    if stage == "headers":

        async def blocked_factory(**kwargs):
            resource = await factory(**kwargs)

            async def wait(_request):
                await asyncio.Event().wait()

            resource.client._transport = httpx.MockTransport(wait)
            return resource

        module_factory = module.create_secure_runtime_http_client
        module.create_secure_runtime_http_client = blocked_factory
        try:
            with pytest.raises(LLMTimeoutError):
                invoke(adapter)
        finally:
            module.create_secure_runtime_http_client = module_factory
    else:

        class Blocked(TrackingStream):
            async def __aiter__(self):
                await asyncio.Event().wait()
                yield b"unreachable"

        factory.stream = Blocked(())
        with pytest.raises(LLMTimeoutError):
            invoke(adapter)
        assert factory.stream.closed
    assert factory.resources[0].client.is_closed


def test_repeated_cancellation_waits_for_http_cleanup_before_propagating(
    setup, monkeypatch
):
    adapter, factory, _ = setup
    started, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    read_started = asyncio.Event()

    class Blocked(TrackingStream):
        async def __aiter__(self):
            read_started.set()
            await asyncio.Event().wait()
            yield b"unreachable"

    factory.stream = Blocked(())

    async def slow_close_factory(**kwargs):
        resource = await factory(**kwargs)
        original = resource.client.aclose

        async def close():
            started.set()
            await release.wait()
            await original()
            finished.set()

        monkeypatch.setattr(resource.client, "aclose", close)
        return resource

    monkeypatch.setattr(module, "create_secure_runtime_http_client", slow_close_factory)

    async def exercise():
        task = asyncio.create_task(
            adapter.embed(
                request=EmbeddingRequest(("first", "second")), target=target()
            )
        )
        await read_started.wait()
        task.cancel()
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()

    asyncio.run(exercise())
    assert factory.stream.closed and factory.resources[0].client.is_closed


def test_cancellation_settles_tokenization_thread_before_returning(setup, monkeypatch):
    adapter, factory, encoding = setup
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def blocked(_text):
        started.set()
        release.wait()
        finished.set()
        return range(1)

    monkeypatch.setattr(encoding, "encode_ordinary", blocked)

    async def exercise():
        task = asyncio.create_task(
            adapter.embed(request=EmbeddingRequest(("first",)), target=target())
        )
        try:
            await asyncio.to_thread(started.wait)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()

    asyncio.run(exercise())
    assert factory.resources == []


@pytest.mark.parametrize(
    "status,expected",
    [(200, LLMProviderUnavailableError), (401, LLMAuthenticationError)],
)
def test_cleanup_failure_is_safe_and_preserves_original_provider_error(
    setup, monkeypatch, status, expected
):
    adapter, factory, _ = setup
    factory.status = status

    async def failing_close_factory(**kwargs):
        resource = await factory(**kwargs)
        original = resource.client.aclose

        async def close():
            await original()
            raise RuntimeError(f"private cleanup detail {SECRET}")

        monkeypatch.setattr(resource.client, "aclose", close)
        return resource

    monkeypatch.setattr(
        module, "create_secure_runtime_http_client", failing_close_factory
    )
    with pytest.raises(expected) as raised:
        invoke(adapter)
    assert "private" not in str(raised.value)
    assert factory.resources[0].client.is_closed


def test_concurrent_invocations_use_isolated_credentials_and_clients(setup):
    adapter, factory, _ = setup

    # Each HTTP response owns its own stream, even when invocations overlap.
    async def isolated_factory(**kwargs):
        local = Factory()
        resource = await local(**kwargs)
        factory.resources.append(resource)
        original = resource.client._transport

        async def respond(outgoing):
            factory.calls.append(outgoing)
            await asyncio.sleep(0)
            return await original.handle_async_request(outgoing)

        resource.client._transport = httpx.MockTransport(respond)
        return resource

    original_factory = module.create_secure_runtime_http_client
    module.create_secure_runtime_http_client = isolated_factory

    async def exercise():
        return await asyncio.gather(
            *(
                adapter.embed(
                    request=EmbeddingRequest(("first", "second")),
                    target=target(secret=key),
                )
                for key in ("tenant-one", "tenant-two")
            )
        )

    try:
        assert len(asyncio.run(exercise())) == 2
    finally:
        module.create_secure_runtime_http_client = original_factory
    assert {request.headers["authorization"] for request in factory.calls} == {
        "Bearer tenant-one",
        "Bearer tenant-two",
    }
    assert len({id(resource.client) for resource in factory.resources}) == 2
    assert all(resource.client.is_closed for resource in factory.resources)


def test_real_secure_factory_pins_dns_preserves_tls_authority_and_disables_redirects(
    setup, monkeypatch
):
    import socket

    adapter, _, _ = setup
    observed = []

    async def respond(request):
        observed.append(request)
        return httpx.Response(
            302,
            headers={"location": "https://attacker.invalid/"},
            stream=TrackingStream(()),
        )

    monkeypatch.setattr(
        httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(respond)
    )
    monkeypatch.setattr(
        module, "create_secure_runtime_http_client", create_secure_runtime_http_client
    )

    class Resolver:
        async def resolve(self, *, host, port):
            assert (host, port) == ("api.openai.com", 443)
            return (ResolvedAddress("8.8.8.8", socket.AF_INET),)

    with pytest.raises(LLMUnknownProviderError):
        invoke(replace(adapter, resolver=Resolver()))
    assert len(observed) == 1
    assert str(observed[0].url) == "https://8.8.8.8/v1/embeddings"
    assert observed[0].headers["host"] == "api.openai.com"
    assert observed[0].extensions["sni_hostname"] == "api.openai.com"


@pytest.mark.parametrize(
    "timeout", [True, False, None, "10", 0, -1, float("nan"), float("inf")]
)
def test_invalid_timeout_configuration_is_rejected(timeout):
    with pytest.raises(ValueError):
        OpenAIEmbeddingAdapter(timeout_seconds=timeout)


def test_embedding_execution_has_no_provider_sdk_or_litellm_imports():
    for path in (
        Path(module.__file__),
        Path(module.__file__).with_name("_embedding_tokenizer.py"),
    ):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else (
                    [node.module]
                    if isinstance(node, ast.ImportFrom) and node.module
                    else []
                )
            )
            assert all(not name.startswith(("litellm", "openai")) for name in names)
