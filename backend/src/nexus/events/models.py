from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from nexus.events.types import EventType


class EventEnvelope(BaseModel):
    """Transport-independent contract for an internal NEXUS event."""

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(min_length=1)
    event_type: EventType
    version: int = Field(ge=1)
    timestamp: datetime
    request_id: str = Field(min_length=1)
    data: dict[str, Any]

    @classmethod
    def create(
        cls,
        *,
        event_type: EventType,
        request_id: str,
        data: dict[str, Any],
    ) -> "EventEnvelope":
        """Create a version-one event with a generated ID and UTC timestamp."""
        return cls(
            event_id=f"evt_{uuid4().hex}",
            event_type=event_type,
            version=1,
            timestamp=datetime.now(UTC),
            request_id=request_id,
            data=data,
        )
