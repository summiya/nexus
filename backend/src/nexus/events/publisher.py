from typing import Protocol

from nexus.events.models import EventEnvelope


class EventPublisher(Protocol):
    """Application-facing contract for publishing internal NEXUS events."""

    async def publish(self, event: EventEnvelope) -> None:
        """Publish an event or propagate the publishing failure."""
        ...
