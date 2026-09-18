"""Streaming Conversation message use case."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
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
        text_parts: list[str] = []
        usage: LLMUsage | None = None
        finish_reason = GenerationFinishReason.UNKNOWN

        try:
            yield GenerationStarted(
                conversation_public_id=self.conversation.public_id,
                generation_public_id=self.generation.public_id,
                model=self.generation.model,
            )

            async for event in self._events():
                usage, finish_reason, output, failure_kind = self._process_event(
                    event,
                    text_parts=text_parts,
                    usage=usage,
                    finish_reason=finish_reason,
                )
                if failure_kind is not None:
                    raise _ConversationStreamFailure(failure_kind)
                if output is not None:
                    yield output

            if not text_parts:
                raise _ConversationStreamFailure("empty_assistant_response")

            assistant_message = Message(
                public_id=uuid4(),
                conversation_public_id=self.conversation.public_id,
                role=ConversationMessageRole.ASSISTANT,
                content="".join(text_parts),
                created_at=datetime.now(UTC),
            )
            completed_generation = replace(
                self.generation,
                assistant_message_public_id=assistant_message.public_id,
                status=GenerationStatus.COMPLETED,
                finish_reason=finish_reason,
                input_tokens=usage.input_tokens if usage is not None else 0,
                output_tokens=usage.output_tokens if usage is not None else 0,
                total_tokens=usage.total_tokens if usage is not None else 0,
                completed_at=datetime.now(UTC),
                error_kind=None,
            )
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

            if usage is not None:
                yield GenerationUsage(
                    generation_public_id=self.generation.public_id,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    total_tokens=usage.total_tokens,
                )
            yield GenerationCompleted(
                conversation_public_id=self.conversation.public_id,
                generation_public_id=self.generation.public_id,
                assistant_message_public_id=assistant_message.public_id,
                finish_reason=finish_reason,
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
        *,
        text_parts: list[str],
        usage: LLMUsage | None,
        finish_reason: GenerationFinishReason,
    ) -> tuple[
        LLMUsage | None,
        GenerationFinishReason,
        ConversationEvent | None,
        str | None,
    ]:
        if isinstance(event, LLMTextDeltaEvent):
            text_parts.append(event.delta)
            return (
                usage,
                finish_reason,
                MessageDelta(
                    conversation_public_id=self.conversation.public_id,
                    generation_public_id=self.generation.public_id,
                    delta=event.delta,
                ),
                None,
            )
        if isinstance(event, LLMUsageEvent):
            return event.usage, finish_reason, None, None
        if isinstance(event, LLMCompletedEvent):
            return usage, _to_generation_finish_reason(event), None, None
        if isinstance(event, LLMErrorEvent):
            return usage, finish_reason, None, event.kind.value
        if isinstance(
            event,
            (
                LLMToolCallStartedEvent,
                LLMToolCallDeltaEvent,
                LLMToolCallCompletedEvent,
            ),
        ):
            return usage, finish_reason, None, "tool_calls_unsupported"
        return usage, finish_reason, None, None

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
        upstream: AsyncIterator[LLMEvent] | None = None
        phase_a_committed = False
        try:
            prepared = await self.persistence.prepare_generation(
                organization_public_id=request.organization_public_id,
                conversation=conversation,
                message=message,
                generation=generation,
                history_limit=self.history_limit,
            )
            phase_a_committed = True
            llm_request = LLMRequest(
                model=model,
                messages=tuple(_to_llm_message(item) for item in prepared.history),
                tools=(),
            )
            upstream = self.llm_stream.execute(llm_request)
            first_event = await anext(upstream)
        except LLMError as exc:
            if phase_a_committed:
                await self._persist_failure(request, generation, exc.kind.value)
            await _close_iterator(upstream)
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "The language model service is unavailable.",
                retryable=True,
            ) from exc
        except StopAsyncIteration as exc:
            if phase_a_committed:
                await self._persist_failure(
                    request, generation, "empty_provider_stream"
                )
            await _close_iterator(upstream)
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "The language model service is unavailable.",
                retryable=True,
            ) from exc
        except Exception:
            if phase_a_committed:
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

        return PreparedConversationStream(
            service=self,
            request=request,
            conversation=conversation,
            generation=generation,
            upstream=upstream,
            first_event=first_event,
        )

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
