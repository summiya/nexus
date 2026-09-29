from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from uuid import uuid4

import httpx
import pytest

from nexus.infrastructure.model_providers.outbound_endpoint import HostResolver
from nexus.infrastructure.model_providers.runtime_http import (
    RuntimeDeadline,
    SecureRuntimeHTTPClient,
)
from nexus.llm.domain import (
    LLMAuthenticationError,
    LLMCompletedEvent,
    LLMErrorEvent,
    LLMEvent,
    LLMMessage,
    LLMRequest,
    LLMRole,
    LLMStartedEvent,
    LLMTextDeltaEvent,
    LLMTimeoutError,
)
from nexus.llm.infrastructure.adapters.litellm.errors import LiteLLMExceptionTypes
from nexus.llm.infrastructure.adapters.litellm.runtime_adapter import (
    LiteLLMRuntimeAdapter,
)
from nexus.model_providers.domain import (
    AnthropicSettings,
    AzureOpenAISettings,
    ConfiguredModelId,
    GeminiSettings,
    OpenAICompatibleSettings,
    OpenAISettings,
    OrganizationProviderId,
    ProviderCredentialSecret,
    ProviderType,
    ResolvedChatModel,
)

SECRET = "sentinel-runtime-secret"


class FakeAuthenticationFailure(Exception):
    pass


class TrackingStream:
    def __init__(self, chunks: list[object], error: Exception | None = None) -> None:
        self.chunks = chunks
        self.error = error
        self.closed = False

    def __aiter__(self) -> TrackingStream:
        return self

    async def __anext__(self) -> object:
        if self.chunks:
            return self.chunks.pop(0)
        if self.error is not None:
            error = self.error
            self.error = None
            raise error
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.closed = True


class BlockingTrackingStream(TrackingStream):
    def __init__(self) -> None:
        super().__init__([])
        self.read_started = asyncio.Event()
        self.release = asyncio.Event()

    async def __anext__(self) -> object:
        self.read_started.set()
        await self.release.wait()
        raise StopAsyncIteration


@dataclass
class FakeLiteLLMClient:
    response: object = field(default_factory=lambda: _completion_response())
    stream_value: TrackingStream = field(
        default_factory=lambda: TrackingStream(_stream_chunks())
    )
    error: Exception | None = None
    calls: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    exception_types: LiteLLMExceptionTypes = field(
        default_factory=lambda: LiteLLMExceptionTypes(
            authentication=(FakeAuthenticationFailure,)
        )
    )

    async def acompletion(self, **kwargs: object) -> object:
        self.calls.append(("generate", kwargs))
        if self.error is not None:
            raise self.error
        return self.response

    async def astream(self, **kwargs: object) -> AsyncIterator[object]:
        self.calls.append(("stream", kwargs))
        if self.error is not None:
            raise self.error
        return self.stream_value


@dataclass
class FakeHTTPClientFactory:
    resources: list[SecureRuntimeHTTPClient] = field(default_factory=list)
    endpoints: list[str] = field(default_factory=list)
    deadline_seconds: float | None = None

    async def __call__(
        self,
        *,
        endpoint: str,
        resolver: HostResolver,
        timeout_seconds: float,
    ) -> SecureRuntimeHTTPClient:
        del resolver
        assert timeout_seconds == 30
        self.endpoints.append(endpoint)
        resource = SecureRuntimeHTTPClient(
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(lambda _request: httpx.Response(200)),
                trust_env=False,
                follow_redirects=False,
            ),
            deadline=RuntimeDeadline.start(self.deadline_seconds or timeout_seconds),
        )
        self.resources.append(resource)
        return resource


def _target(
    *,
    provider_type: ProviderType = ProviderType.OPENAI,
    model: str = "authoritative-provider-model",
    secret: str = SECRET,
) -> ResolvedChatModel:
    settings = {
        ProviderType.OPENAI: OpenAISettings(),
        ProviderType.ANTHROPIC: AnthropicSettings(),
        ProviderType.AZURE_OPENAI: AzureOpenAISettings(
            endpoint="https://azure.example",
            api_version="2026-09-01",
        ),
        ProviderType.GEMINI: GeminiSettings(),
        ProviderType.OPENAI_COMPATIBLE: OpenAICompatibleSettings(
            base_url="https://compatible.example/custom/v1"
        ),
    }[provider_type]
    return ResolvedChatModel(
        model_id=ConfiguredModelId(uuid4()),
        provider_id=OrganizationProviderId(uuid4()),
        provider_type=provider_type,
        provider_model_name=model,
        settings=settings,
        credential=ProviderCredentialSecret(secret),
    )


def _request() -> LLMRequest:
    return LLMRequest(
        model="untrusted-request-model",
        messages=(LLMMessage(role=LLMRole.USER, content="hello"),),
    )


def _completion_response() -> dict[str, object]:
    return {
        "id": "response-1",
        "model": "provider-model",
        "choices": [
            {
                "message": {"role": "assistant", "content": "hello"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }


def _stream_chunks() -> list[object]:
    return [
        {"choices": [{"delta": {"content": "hel"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "lo"}, "finish_reason": "stop"}]},
        {
            "choices": [],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 2,
                "total_tokens": 3,
            },
        },
    ]


def _adapter(
    client: FakeLiteLLMClient,
    factory: FakeHTTPClientFactory,
) -> LiteLLMRuntimeAdapter:
    return LiteLLMRuntimeAdapter(
        timeout_seconds=30,
        http_client_factory=factory,
        litellm_client=client,
    )


def test_generate_uses_authoritative_target_and_closes_request_resources() -> None:
    client = FakeLiteLLMClient()
    factory = FakeHTTPClientFactory()

    response = asyncio.run(
        _adapter(client, factory).generate(request=_request(), target=_target())
    )

    assert response.message.content == "hello"
    assert client.calls[0][0] == "generate"
    arguments = client.calls[0][1]
    assert arguments["model"] == "authoritative-provider-model"
    assert arguments["custom_llm_provider"] == "openai"
    assert arguments["api_key"] == SECRET
    assert "untrusted-request-model" not in str(arguments["model"])
    assert factory.resources[0].client.is_closed


def test_openai_compatible_preserves_custom_base_path() -> None:
    client = FakeLiteLLMClient()
    factory = FakeHTTPClientFactory()

    asyncio.run(
        _adapter(client, factory).generate(
            request=_request(),
            target=_target(provider_type=ProviderType.OPENAI_COMPATIBLE),
        )
    )

    assert factory.endpoints == ["https://compatible.example/custom/v1"]
    assert client.calls[0][1]["api_base"] == (
        "https://compatible.example/custom/v1"
    )


def test_stream_reuses_existing_event_mapping_and_closes_resources() -> None:
    client = FakeLiteLLMClient()
    factory = FakeHTTPClientFactory()

    async def consume() -> list[LLMEvent]:
        return [
            event
            async for event in _adapter(client, factory).stream(
                request=_request(), target=_target()
            )
        ]

    events = asyncio.run(consume())

    assert isinstance(events[0], LLMStartedEvent)
    assert [event.delta for event in events if isinstance(event, LLMTextDeltaEvent)] == [
        "hel",
        "lo",
    ]
    assert isinstance(events[-1], LLMCompletedEvent)
    assert client.stream_value.closed
    assert factory.resources[0].client.is_closed


def test_provider_failure_before_stream_is_normalized_and_cleaned_up(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = FakeLiteLLMClient(error=FakeAuthenticationFailure("unsafe secret detail"))
    factory = FakeHTTPClientFactory()

    async def consume() -> None:
        async for _event in _adapter(client, factory).stream(
            request=_request(), target=_target()
        ):
            pass

    with pytest.raises(LLMAuthenticationError) as captured:
        asyncio.run(consume())

    assert str(captured.value) == "LLM provider request failed"
    assert SECRET not in str(captured.value)
    assert "unsafe secret detail" not in str(captured.value)
    assert SECRET not in repr(captured.value.safe_details)
    assert SECRET not in caplog.text
    assert all(SECRET not in endpoint for endpoint in factory.endpoints)
    assert factory.resources[0].client.is_closed


def test_midstream_failure_yields_safe_error_and_closes_everything() -> None:
    stream = TrackingStream(
        [{"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]}],
        error=FakeAuthenticationFailure("unsafe secret detail"),
    )
    client = FakeLiteLLMClient(stream_value=stream)
    factory = FakeHTTPClientFactory()

    async def consume() -> list[LLMEvent]:
        return [
            event
            async for event in _adapter(client, factory).stream(
                request=_request(), target=_target()
            )
        ]

    events = asyncio.run(consume())

    error = next(event for event in events if isinstance(event, LLMErrorEvent))
    assert error.message == "LLM provider request failed"
    assert SECRET not in repr(events)
    assert stream.closed
    assert factory.resources[0].client.is_closed


def test_early_stream_close_closes_upstream_and_transport() -> None:
    client = FakeLiteLLMClient()
    factory = FakeHTTPClientFactory()

    async def consume_one() -> None:
        stream = _adapter(client, factory).stream(request=_request(), target=_target())
        assert isinstance(await anext(stream), LLMStartedEvent)
        await stream.aclose()

    asyncio.run(consume_one())

    assert client.stream_value.closed
    assert factory.resources[0].client.is_closed


def test_target_and_adapter_representations_never_contain_secret() -> None:
    adapter = _adapter(FakeLiteLLMClient(), FakeHTTPClientFactory())
    target = _target()

    assert SECRET not in repr(target)
    assert SECRET not in repr(adapter)


def test_generate_cancellation_closes_transport_before_propagating() -> None:
    factory = FakeHTTPClientFactory()
    started = asyncio.Event()

    class BlockingClient(FakeLiteLLMClient):
        async def acompletion(self, **kwargs: object) -> object:
            self.calls.append(("generate", kwargs))
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    async def cancel() -> None:
        task = asyncio.create_task(
            _adapter(BlockingClient(), factory).generate(
                request=_request(), target=_target()
            )
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel())

    assert factory.resources[0].client.is_closed


def test_stream_cancellation_closes_upstream_and_transport() -> None:
    stream_value = BlockingTrackingStream()
    client = FakeLiteLLMClient(stream_value=stream_value)
    factory = FakeHTTPClientFactory()

    async def cancel() -> None:
        stream = _adapter(client, factory).stream(
            request=_request(), target=_target()
        )
        assert isinstance(await anext(stream), LLMStartedEvent)
        task = asyncio.create_task(anext(stream))
        await stream_value.read_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel())

    assert stream_value.closed
    assert factory.resources[0].client.is_closed


def test_runtime_deadline_closes_transport() -> None:
    factory = FakeHTTPClientFactory(deadline_seconds=0.01)

    class BlockingClient(FakeLiteLLMClient):
        async def acompletion(self, **kwargs: object) -> object:
            self.calls.append(("generate", kwargs))
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    with pytest.raises(LLMTimeoutError) as captured:
        asyncio.run(
            _adapter(BlockingClient(), factory).generate(
                request=_request(), target=_target()
            )
        )

    assert str(captured.value) == "LLM provider request timed out."
    assert factory.resources[0].client.is_closed


def test_concurrent_runtime_requests_keep_targets_and_credentials_isolated() -> None:
    client = FakeLiteLLMClient()
    factory = FakeHTTPClientFactory()
    adapter = _adapter(client, factory)

    async def invoke() -> None:
        await asyncio.gather(
            adapter.generate(
                request=_request(),
                target=_target(
                    provider_type=ProviderType.OPENAI,
                    model="openai-model",
                    secret="openai-sentinel-secret",
                ),
            ),
            adapter.generate(
                request=_request(),
                target=_target(
                    provider_type=ProviderType.OPENAI_COMPATIBLE,
                    model="compatible-alias",
                    secret="compatible-sentinel-secret",
                ),
            ),
        )

    asyncio.run(invoke())

    arguments_by_model = {call[1]["model"]: call[1] for call in client.calls}
    assert arguments_by_model["openai-model"]["api_key"] == (
        "openai-sentinel-secret"
    )
    assert "api_base" not in arguments_by_model["openai-model"]
    assert arguments_by_model["compatible-alias"]["api_key"] == (
        "compatible-sentinel-secret"
    )
    assert arguments_by_model["compatible-alias"]["api_base"] == (
        "https://compatible.example/custom/v1"
    )
    assert all(resource.client.is_closed for resource in factory.resources)
