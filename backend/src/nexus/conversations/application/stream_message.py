"""Streaming Conversation message use case."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from nexus.conversations.application.events import (
    ConversationEvent,
    GenerationCompleted,
    GenerationError,
    GenerationStarted,
    GenerationUsage,
    MessageDelta,
)
from nexus.conversations.domain import (
    Conversation,
    ConversationMessageRole,
    Generation,
    GenerationFinishReason,
    GenerationStatus,
    Message,
)
from nexus.conversations.ports.persistence import ConversationPersistence
from nexus.errors import ErrorCode, NexusError
from nexus.llm.application import Stream
from nexus.llm.domain import (
    LLMCompletedEvent,
    LLMError,
    LLMErrorEvent,
    LLMEvent,
    LLMMessage,
    LLMRequest,
    LLMRole,
    LLMTextDeltaEvent,
    LLMToolCallCompletedEvent,
    LLMToolCallDeltaEvent,
    LLMToolCallStartedEvent,
    LLMUsage,
    LLMUsageEvent,
)


@dataclass(frozen=True)
class StreamConversationMessageRequest:
    organization_public_id: UUID
    user_public_id: UUID
    conversation_public_id: UUID
    content: str
    model: str


@dataclass
class _StreamState:
    text_parts: list[str] = field(default_factory=list)
    usage: LLMUsage | None = None
    finish_reason: GenerationFinishReason = GenerationFinishReason.UNKNOWN


@dataclass
class PreparedConversationStream:
    """A preflighted stream returned after Phase A and first-event success."""

    service: StreamConversationMessage
    request: StreamConversationMessageRequest
    conversation: Conversation
    generation: Generation
    upstream: AsyncIterator[LLMEvent]
    first_event: LLMEvent
    closed: bool = False

    def __aiter__(self) -> AsyncIterator[ConversationEvent]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[ConversationEvent]:
        state = _StreamState()

        try:
            yield GenerationStarted(
                conversation_public_id=self.conversation.public_id,
                generation_public_id=self.generation.public_id,
                model=self.generation.model,
            )

            async for event in self._events():
                output = self._process_event(event, state)
                if output is not None:
                    yield output

            assistant_message, completed_generation = self._build_completion(state)
            try:
                await self.service.persistence.complete_generation(
                    organization_public_id=self.request.organization_public_id,
                    assistant_message=assistant_message,
                    generation=completed_generation,
                )
            except Exception:  # noqa: BLE001 - persistence failure becomes a safe event
                await self.service._persist_failure(
                    self.request,
                    self.generation,
                    "persistence_failure",
                )
                yield GenerationError(
                    generation_public_id=self.generation.public_id,
                    kind="persistence_failure",
                    message="The generation could not be completed.",
                )
                return

            if state.usage is not None:
                yield GenerationUsage(
                    generation_public_id=self.generation.public_id,
                    input_tokens=state.usage.input_tokens,
                    output_tokens=state.usage.output_tokens,
                    total_tokens=state.usage.total_tokens,
                )
            yield GenerationCompleted(
                conversation_public_id=self.conversation.public_id,
                generation_public_id=self.generation.public_id,
                assistant_message_public_id=assistant_message.public_id,
                finish_reason=state.finish_reason,
            )
        except asyncio.CancelledError:
            await self.service._persist_cancelled(self.request, self.generation)
            raise
        except _ConversationStreamFailure as exc:
            await self.service._persist_failure(
                self.request,
                self.generation,
                exc.kind,
            )
            yield GenerationError(
                generation_public_id=self.generation.public_id,
                kind=exc.kind,
                message="The generation could not be completed.",
            )
        except LLMError as exc:
            await self.service._persist_failure(
                self.request,
                self.generation,
                exc.kind.value,
            )
            yield GenerationError(
                generation_public_id=self.generation.public_id,
                kind=exc.kind.value,
                message="The generation could not be completed.",
            )
        finally:
            await self.aclose()

    async def _events(self) -> AsyncIterator[LLMEvent]:
        yield self.first_event
        async for event in self.upstream:
            yield event

    def _process_event(
        self,
        event: LLMEvent,
        state: _StreamState,
    ) -> ConversationEvent | None:
        if isinstance(event, LLMTextDeltaEvent):
            state.text_parts.append(event.delta)
            return MessageDelta(
                conversation_public_id=self.conversation.public_id,
                generation_public_id=self.generation.public_id,
                delta=event.delta,
            )
        if isinstance(event, LLMUsageEvent):
            state.usage = event.usage
            return None
        if isinstance(event, LLMCompletedEvent):
            state.finish_reason = _to_generation_finish_reason(event)
            return None
        if isinstance(event, LLMErrorEvent):
            raise _ConversationStreamFailure(event.kind.value)
        if isinstance(
            event,
            (
                LLMToolCallStartedEvent,
                LLMToolCallDeltaEvent,
                LLMToolCallCompletedEvent,
            ),
        ):
            raise _ConversationStreamFailure("tool_calls_unsupported")
        return None

    def _build_completion(self, state: _StreamState) -> tuple[Message, Generation]:
        if not state.text_parts:
            raise _ConversationStreamFailure("empty_assistant_response")

        assistant_message = Message(
            public_id=uuid4(),
            conversation_public_id=self.conversation.public_id,
            role=ConversationMessageRole.ASSISTANT,
            content="".join(state.text_parts),
            created_at=datetime.now(UTC),
        )
        completed_generation = replace(
            self.generation,
            assistant_message_public_id=assistant_message.public_id,
            status=GenerationStatus.COMPLETED,
            finish_reason=state.finish_reason,
            input_tokens=state.usage.input_tokens if state.usage is not None else 0,
            output_tokens=state.usage.output_tokens if state.usage is not None else 0,
            total_tokens=state.usage.total_tokens if state.usage is not None else 0,
            completed_at=datetime.now(UTC),
            error_kind=None,
        )
        return assistant_message, completed_generation

    async def aclose(self) -> None:
        if self.closed:
            return
        self.closed = True
        close = getattr(self.upstream, "aclose", None)
        if not callable(close):
            return
        try:
            await close()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - cleanup must not hide the primary error
            return


@dataclass(frozen=True)
class StreamConversationMessage:
    persistence: ConversationPersistence
    llm_stream: Stream
    history_limit: int
    message_max_length: int

    async def prepare(
        self,
        request: StreamConversationMessageRequest,
    ) -> PreparedConversationStream:
        content = request.content.strip()
        model = request.model.strip()
        if not content or len(content) > self.message_max_length:
            raise NexusError(ErrorCode.VALIDATION_ERROR, "Invalid message content.")
        if not model:
            raise NexusError(ErrorCode.VALIDATION_ERROR, "Invalid model.")

        conversation = await self.persistence.get_conversation(
            organization_public_id=request.organization_public_id,
            conversation_public_id=request.conversation_public_id,
        )
        if conversation is None or (
            conversation.workspace_public_id is None
            and conversation.created_by_user_public_id != request.user_public_id
        ):
            raise NexusError(
                ErrorCode.NOT_FOUND, "The requested resource was not found."
            )
        if conversation.workspace_public_id is not None:
            raise NexusError(
                ErrorCode.FORBIDDEN,
                "You are not allowed to perform this action.",
            )

        now = datetime.now(UTC)
        message = Message(
            public_id=uuid4(),
            conversation_public_id=conversation.public_id,
            role=ConversationMessageRole.USER,
            content=content,
            created_at=now,
        )
        generation = Generation(
            public_id=uuid4(),
            conversation_public_id=conversation.public_id,
            user_message_public_id=message.public_id,
            model=model,
            status=GenerationStatus.RUNNING,
            started_at=now,
        )
        prepared = await self.persistence.prepare_generation(
            organization_public_id=request.organization_public_id,
            conversation=conversation,
            message=message,
            generation=generation,
            history_limit=self.history_limit,
        )
        try:
            llm_request = LLMRequest(
                model=model,
                messages=tuple(_to_llm_message(item) for item in prepared.history),
                tools=(),
            )
        except Exception:
            await self._persist_failure(
                request,
                generation,
                "stream_initialization_failure",
            )
            raise

        upstream, first_event = await self._preflight_stream(
            request=request,
            generation=generation,
            llm_request=llm_request,
        )

        return PreparedConversationStream(
            service=self,
            request=request,
            conversation=conversation,
            generation=generation,
            upstream=upstream,
            first_event=first_event,
        )

    async def _preflight_stream(
        self,
        *,
        request: StreamConversationMessageRequest,
        generation: Generation,
        llm_request: LLMRequest,
    ) -> tuple[AsyncIterator[LLMEvent], LLMEvent]:
        upstream: AsyncIterator[LLMEvent] | None = None
        try:
            upstream = self.llm_stream.execute(llm_request)
            first_event = await anext(upstream)
        except asyncio.CancelledError:
            await _close_iterator_during_cancellation(upstream)
            await self._persist_cancelled(request, generation)
            raise
        except LLMError as exc:
            await self._persist_failure(request, generation, exc.kind.value)
            await _close_iterator(upstream)
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "The language model service is unavailable.",
                retryable=True,
            ) from exc
        except StopAsyncIteration as exc:
            await self._persist_failure(request, generation, "empty_provider_stream")
            await _close_iterator(upstream)
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "The language model service is unavailable.",
                retryable=True,
            ) from exc
        except Exception:
            await self._persist_failure(
                request,
                generation,
                "stream_initialization_failure",
            )
            await _close_iterator(upstream)
            raise

        if isinstance(first_event, LLMErrorEvent):
            await self._persist_failure(request, generation, first_event.kind.value)
            await _close_iterator(upstream)
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "The language model service is unavailable.",
                retryable=True,
            )
        if isinstance(
            first_event,
            (
                LLMToolCallStartedEvent,
                LLMToolCallDeltaEvent,
                LLMToolCallCompletedEvent,
            ),
        ):
            await self._persist_failure(request, generation, "tool_calls_unsupported")
            await _close_iterator(upstream)
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "The requested generation could not be completed.",
            )
        return upstream, first_event

    async def _persist_failure(
        self,
        request: StreamConversationMessageRequest,
        generation: Generation,
        kind: str,
    ) -> None:
        try:
            await self.persistence.fail_generation(
                organization_public_id=request.organization_public_id,
                generation=replace(
                    generation,
                    status=GenerationStatus.FAILED,
                    completed_at=datetime.now(UTC),
                    error_kind=kind,
                ),
            )
        except Exception:  # noqa: BLE001 - cancellation persistence is best effort
            return

    async def _persist_cancelled(
        self,
        request: StreamConversationMessageRequest,
        generation: Generation,
    ) -> None:
        try:
            await self.persistence.cancel_generation(
                organization_public_id=request.organization_public_id,
                generation=replace(
                    generation,
                    status=GenerationStatus.CANCELLED,
                    completed_at=datetime.now(UTC),
                ),
            )
        except Exception:  # noqa: BLE001 - cancellation persistence is best effort
            return


class _ConversationStreamFailure(Exception):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


def _to_llm_message(message: Message) -> LLMMessage:
    role = {
        ConversationMessageRole.SYSTEM: LLMRole.SYSTEM,
        ConversationMessageRole.USER: LLMRole.USER,
        ConversationMessageRole.ASSISTANT: LLMRole.ASSISTANT,
    }[message.role]
    return LLMMessage(role=role, content=message.content)


def _to_generation_finish_reason(event: LLMCompletedEvent) -> GenerationFinishReason:
    try:
        return GenerationFinishReason(event.finish_reason.value)
    except ValueError:
        return GenerationFinishReason.UNKNOWN


async def _close_iterator(iterator: AsyncIterator[LLMEvent] | None) -> None:
    if iterator is None:
        return
    close = getattr(iterator, "aclose", None)
    if not callable(close):
        return
    try:
        await close()
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - upstream cleanup is best effort
        return


async def _close_iterator_during_cancellation(
    iterator: AsyncIterator[LLMEvent] | None,
) -> None:
    """Attempt provider cleanup without replacing the original cancellation."""
    try:
        await _close_iterator(iterator)
    except BaseException:  # noqa: BLE001 - cancellation remains the primary outcome
        return
