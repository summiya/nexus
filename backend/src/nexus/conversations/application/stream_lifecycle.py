"""Conversation stream ownership and terminal lifecycle handling."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Coroutine
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Self
from uuid import UUID

from nexus.conversations.application.events import (
    ConversationEvent,
    GenerationCompleted,
    GenerationError,
    GenerationStarted,
)
from nexus.conversations.application.stream_events import (
    ConversationEventAssembler,
    ConversationStreamAssemblyError,
)
from nexus.conversations.domain import (
    Conversation,
    Generation,
    GenerationStatus,
    Message,
)
from nexus.conversations.ports.persistence import ConversationPersistence
from nexus.errors import ErrorCode, NexusError
from nexus.llm.domain import (
    LLMError,
    LLMErrorEvent,
    LLMEvent,
    LLMToolCallCompletedEvent,
    LLMToolCallDeltaEvent,
    LLMToolCallStartedEvent,
)
from nexus.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ConversationStreamLifecycle:
    """Own a Conversation generation's terminal state and normalized LLM stream."""

    persistence: ConversationPersistence
    organization_public_id: UUID
    conversation: Conversation
    generation: Generation
    _upstream: AsyncIterator[LLMEvent] | None = field(default=None, init=False)
    _first_event: LLMEvent | None = field(default=None, init=False)
    _provider_closed: bool = field(default=False, init=False)
    _terminal_resolved: bool = field(default=False, init=False)
    _terminal_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock,
        init=False,
        repr=False,
    )

    async def start(self, upstream: AsyncIterator[LLMEvent]) -> Self:
        """Take ownership of a normalized provider iterator and preflight it."""

        if self._upstream is not None:
            raise RuntimeError("Conversation stream lifecycle has already started")
        self._upstream = upstream

        try:
            first_event = await anext(upstream)
        except asyncio.CancelledError:
            await self.aclose()
            raise
        except (LLMError, StopAsyncIteration) as exc:
            kind = (
                exc.kind.value
                if isinstance(exc, LLMError)
                else "incomplete_provider_stream"
            )
            await self._fail_preflight(kind)
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "The language model service is unavailable.",
                retryable=True,
            ) from exc
        except Exception:
            await self._fail_preflight("stream_initialization_failure")
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
            self._first_event = first_event
            return self

        await self._fail_preflight(kind)
        raise NexusError(ErrorCode.SERVICE_UNAVAILABLE, message, retryable=retryable)

    def __aiter__(self) -> AsyncIterator[ConversationEvent]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[ConversationEvent]:
        if self._upstream is None or self._first_event is None:
            raise RuntimeError("Conversation stream lifecycle has not been started")

        assembler = ConversationEventAssembler(self.conversation, self.generation)
        try:
            yield GenerationStarted(
                conversation_public_id=self.conversation.public_id,
                generation_public_id=self.generation.public_id,
                model=self.generation.model,
            )

            async for event in self._events():
                output = assembler.process(event)
                if output is not None:
                    yield output

            assistant_message, completed_generation = assembler.build_completion()
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

            usage_event = assembler.usage_event()
            if usage_event is not None:
                yield usage_event
            yield GenerationCompleted(
                conversation_public_id=self.conversation.public_id,
                generation_public_id=self.generation.public_id,
                assistant_message_public_id=assistant_message.public_id,
                finish_reason=assembler.finish_reason,
            )
        except asyncio.CancelledError:
            raise
        except ConversationStreamAssemblyError as exc:
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
        assert self._first_event is not None
        assert self._upstream is not None
        yield self._first_event
        async for event in self._upstream:
            yield event

    async def fail(self, kind: str) -> bool | None:
        """Persist a terminal failure before or during provider streaming."""

        return await self._transition_terminal(
            status=GenerationStatus.FAILED,
            error_kind=kind,
        )

    async def cancel(self) -> None:
        """Finish cancellation persistence despite repeated task cancellation."""

        await _finish_cleanup(self._cancel())

    async def _cancel(self) -> None:
        await self._transition_terminal(status=GenerationStatus.CANCELLED)

    async def aclose(self) -> None:
        await _finish_cleanup(self._close())

    async def _close(self) -> None:
        try:
            await self._close_provider_once()
        finally:
            await self._transition_terminal(status=GenerationStatus.CANCELLED)

    async def _fail_preflight(self, kind: str) -> None:
        await _finish_cleanup(self._fail_and_close(kind))

    async def _fail_and_close(self, kind: str) -> None:
        try:
            await self.fail(kind)
        finally:
            await self._close_provider_once()

    async def _close_provider_once(self) -> None:
        if self._provider_closed:
            return
        self._provider_closed = True
        if self._upstream is None:
            return
        close = getattr(self._upstream, "aclose", None)
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

    async def _complete_generation(
        self,
        assistant_message: Message,
        generation: Generation,
    ) -> bool | None:
        async with self._terminal_lock:
            if self._terminal_resolved:
                return False
            try:
                transitioned = await self.persistence.complete_generation(
                    organization_public_id=self.organization_public_id,
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
        transitioned = await self.fail(kind)
        if not transitioned:
            return None
        return GenerationError(
            generation_public_id=self.generation.public_id,
            kind=kind,
            message="The generation could not be completed.",
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
            persist = (
                self.persistence.fail_generation
                if status is GenerationStatus.FAILED
                else self.persistence.cancel_generation
            )
            try:
                transitioned = await persist(
                    organization_public_id=self.organization_public_id,
                    generation=replace(
                        self.generation,
                        status=status,
                        completed_at=datetime.now(UTC),
                        error_kind=error_kind,
                    ),
                )
            except Exception:
                logger.exception(
                    "conversation_terminal_persistence_failed",
                    generation_id=str(self.generation.public_id),
                    status=status.value,
                    error_kind=error_kind,
                )
                return None

            self._terminal_resolved = True
            return transitioned


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
