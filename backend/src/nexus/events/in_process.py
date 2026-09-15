from collections import defaultdict
from collections.abc import Awaitable, Callable

from nexus.events.models import EventEnvelope
from nexus.events.types import EventType

EventHandler = Callable[[EventEnvelope], Awaitable[None]]


class InProcessEventPublisher:
    """Publish events to async handlers in the current process."""

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Register an async handler for one canonical event type."""
        self._handlers[event_type].append(handler)

    async def publish(self, event: EventEnvelope) -> None:
        """Await matching handlers in registration order; failures propagate."""
        for handler in tuple(self._handlers.get(event.event_type, ())):
            await handler(event)
