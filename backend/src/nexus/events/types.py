from enum import StrEnum


class EventType(StrEnum):
    """Canonical names for internal NEXUS events."""

    CONVERSATION_CREATED = "conversation.created"
    MESSAGE_CREATED = "message.created"
    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    MODEL_REQUEST_STARTED = "model.request.started"
    MODEL_REQUEST_COMPLETED = "model.request.completed"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
