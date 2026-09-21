"""Streaming Conversation message use case."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Coroutine
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any
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
from nexus.llm.application import ModelNotAllowedError, ModelPolicy, Stream
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
from nexus.logging import get_logger

logger = get_logger(__name__)


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
    provider_completed: bool = False


@dataclass
class PreparedConversationStream:
    """Own the normalized LLM iterator after successful preflight."""

    service: StreamConversationMessage
    request: StreamConversationMessageRequest
    conversation: Conversation
    generation: Generation
    upstream: AsyncIterator[LLMEvent]
    first_event: LLMEvent
    _provider_closed: bool = field(default=False, init=False)
    _terminal_resolved: bool = field(default=False, init=False)
    _terminal_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock,
        init=False,
        repr=False,
    )

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
            transitioned = await self._complete_generation(
                assistant_message,
                completed_generation,
            )
            if transitioned is None:
                failure = await self._failure_event("persistence_failure")
                if failure is not None:
                    yield failure
                return
            if not transitioned:
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
            raise
        except _ConversationStreamFailure as exc:
            failure = await self._failure_event(exc.kind)
            if failure is not None:
                yield failure
        except LLMError as exc:
            failure = await self._failure_event(exc.kind.value)
            if failure is not None:
                yield failure
        except Exception:
            logger.exception(
                "conversation_stream_processing_failed",
                generation_id=str(self.generation.public_id),
            )
            failure = await self._failure_event("stream_processing_failure")
            if failure is not None:
                yield failure
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
            state.provider_completed = True
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
        if not state.provider_completed:
            raise _ConversationStreamFailure("incomplete_provider_stream")
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

    async def _complete_generation(
        self,
        assistant_message: Message,
        generation: Generation,
    ) -> bool | None:
        async with self._terminal_lock:
            if self._terminal_resolved:
                return False
            try:
                transitioned = await self.service.persistence.complete_generation(
                    organization_public_id=self.request.organization_public_id,
                    assistant_message=assistant_message,
                    generation=generation,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "conversation_completion_persistence_failed",
                    generation_id=str(self.generation.public_id),
                )
                return None

            self._terminal_resolved = True
            return transitioned

    async def _failure_event(self, kind: str) -> GenerationError | None:
        transitioned = await self._transition_terminal(
            status=GenerationStatus.FAILED,
            error_kind=kind,
        )
        if not transitioned:
            return None
        return GenerationError(
            generation_public_id=self.generation.public_id,
            kind=kind,
            message="The generation could not be completed.",
        )

    async def aclose(self) -> None:
        await _finish_cleanup(self._close())

    async def _close(self) -> None:
        try:
            await self._close_provider_once()
        finally:
            await self._transition_terminal(status=GenerationStatus.CANCELLED)

    async def _close_provider_once(self) -> None:
        if self._provider_closed:
            return
        self._provider_closed = True
        close = getattr(self.upstream, "aclose", None)
        if not callable(close):
            return
        try:
            await close()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "conversation_provider_stream_cleanup_failed",
                generation_id=str(self.generation.public_id),
                exc_info=True,
            )

    async def _transition_terminal(
        self,
        *,
        status: GenerationStatus,
        error_kind: str | None = None,
    ) -> bool | None:
        async with self._terminal_lock:
            if self._terminal_resolved:
                return False
            transitioned = await self.service._persist_terminal(
                self.request,
                self.generation,
                status=status,
                error_kind=error_kind,
            )
            if transitioned is not None:
                self._terminal_resolved = True
            return transitioned


@dataclass(frozen=True)
class StreamConversationMessage:
    persistence: ConversationPersistence
    llm_stream: Stream
    model_policy: ModelPolicy
    history_limit: int
    history_max_chars: int
    message_max_length: int

    async def prepare(
        self,
        request: StreamConversationMessageRequest,
    ) -> PreparedConversationStream:
        content = request.content.strip()
        if not content or len(content) > self.message_max_length:
            raise NexusError(ErrorCode.VALIDATION_ERROR, "Invalid message content.")
        try:
            model = self.model_policy.resolve(request.model)
        except ModelNotAllowedError as exc:
            raise NexusError(
                ErrorCode.VALIDATION_ERROR,
                "The requested model is not available.",
            ) from exc

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
        try:
            history = await self.persistence.prepare_generation(
                organization_public_id=request.organization_public_id,
                conversation=conversation,
                message=message,
                generation=generation,
                history_limit=self.history_limit,
            )
        except asyncio.CancelledError:
            await _finish_cleanup(
                self._cleanup_cancellation(request, generation, upstream=None)
            )
            raise
        try:
            bounded_history = _bounded_history(
                history,
                max_chars=self.history_max_chars,
            )
            llm_request = LLMRequest(
                model=model,
                messages=tuple(_to_llm_message(item) for item in bounded_history),
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
            await _finish_cleanup(
                self._cleanup_cancellation(request, generation, upstream=upstream)
            )
            raise
        except (LLMError, StopAsyncIteration) as exc:
            kind = (
                exc.kind.value
                if isinstance(exc, LLMError)
                else "incomplete_provider_stream"
            )
            await self._cleanup_preflight_failure(request, generation, upstream, kind)
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "The language model service is unavailable.",
                retryable=True,
            ) from exc
        except Exception:
            await self._cleanup_preflight_failure(
                request, generation, upstream, "stream_initialization_failure"
            )
            raise

        if isinstance(first_event, LLMErrorEvent):
            kind = first_event.kind.value
            message = "The language model service is unavailable."
            retryable = True
        elif isinstance(
            first_event,
            (
                LLMToolCallStartedEvent,
                LLMToolCallDeltaEvent,
                LLMToolCallCompletedEvent,
            ),
        ):
            kind = "tool_calls_unsupported"
            message = "The requested generation could not be completed."
            retryable = False
        else:
            return upstream, first_event

        await self._cleanup_preflight_failure(request, generation, upstream, kind)
        raise NexusError(ErrorCode.SERVICE_UNAVAILABLE, message, retryable=retryable)

    async def _cleanup_preflight_failure(
        self,
        request: StreamConversationMessageRequest,
        generation: Generation,
        upstream: AsyncIterator[LLMEvent] | None,
        kind: str,
    ) -> None:
        await self._persist_failure(request, generation, kind)
        await _close_iterator(upstream)

    async def _cleanup_cancellation(
        self,
        request: StreamConversationMessageRequest,
        generation: Generation,
        *,
        upstream: AsyncIterator[LLMEvent] | None,
    ) -> None:
        try:
            await _close_iterator(upstream)
        finally:
            await self._persist_cancelled(request, generation)

    async def _persist_failure(
        self,
        request: StreamConversationMessageRequest,
        generation: Generation,
        kind: str,
    ) -> bool | None:
        return await self._persist_terminal(
            request,
            generation,
            status=GenerationStatus.FAILED,
            error_kind=kind,
        )

    async def _persist_cancelled(
        self,
        request: StreamConversationMessageRequest,
        generation: Generation,
    ) -> bool | None:
        return await self._persist_terminal(
            request,
            generation,
            status=GenerationStatus.CANCELLED,
        )

    async def _persist_terminal(
        self,
        request: StreamConversationMessageRequest,
        generation: Generation,
        *,
        status: GenerationStatus,
        error_kind: str | None = None,
    ) -> bool | None:
        persist = (
            self.persistence.fail_generation
            if status is GenerationStatus.FAILED
            else self.persistence.cancel_generation
        )
        try:
            return await persist(
                organization_public_id=request.organization_public_id,
                generation=replace(
                    generation,
                    status=status,
                    completed_at=datetime.now(UTC),
                    error_kind=error_kind,
                ),
            )
        except Exception:
            logger.exception(
                "conversation_terminal_persistence_failed",
                generation_id=str(generation.public_id),
                status=status.value,
                error_kind=error_kind,
            )
            return None


class _ConversationStreamFailure(Exception):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


def _bounded_history(
    history: tuple[Message, ...],
    *,
    max_chars: int,
) -> tuple[Message, ...]:
    """Keep the newest chronological history that fits the configured budget."""

    selected: list[Message] = []
    used_chars = 0
    for message in reversed(history):
        next_size = len(message.content)
        if selected and used_chars + next_size > max_chars:
            break
        if not selected and next_size > max_chars:
            selected.append(message)
            break
        selected.append(message)
        used_chars += next_size
    selected.reverse()
    return tuple(selected)


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
    except Exception:
        logger.warning("conversation_provider_stream_cleanup_failed", exc_info=True)


async def _finish_cleanup(
    cleanup: Coroutine[Any, Any, None],
) -> None:
    """Finish cleanup even if the awaiting request receives another cancellation."""
    task = asyncio.create_task(cleanup)
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            cancellation = exc
        except BaseException:  # noqa: BLE001 - re-raised through task.result below
            break

    if cancellation is not None:
        if not task.cancelled():
            task.exception()
        raise cancellation
    task.result()
