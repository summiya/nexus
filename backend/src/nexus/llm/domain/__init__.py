"""Provider-independent LLM domain contracts."""

from nexus.llm.domain.capabilities import LLMProviderCapabilities
from nexus.llm.domain.errors import (
    LLMAuthenticationError,
    LLMContentRejectedError,
    LLMError,
    LLMErrorKind,
    LLMInvalidRequestError,
    LLMProviderUnavailableError,
    LLMRateLimitedError,
    LLMTimeoutError,
    LLMUnknownProviderError,
)
from nexus.llm.domain.events import (
    LLMCompletedEvent,
    LLMErrorEvent,
    LLMEvent,
    LLMEventType,
    LLMStartedEvent,
    LLMTextDeltaEvent,
    LLMToolCallCompletedEvent,
    LLMToolCallDeltaEvent,
    LLMToolCallStartedEvent,
    LLMUsageEvent,
)
from nexus.llm.domain.messages import LLMMessage, LLMRole
from nexus.llm.domain.requests import LLMRequest
from nexus.llm.domain.responses import LLMFinishReason, LLMResponse
from nexus.llm.domain.tools import LLMToolCall, LLMToolDefinition
from nexus.llm.domain.usage import LLMUsage

__all__ = [
    "LLMAuthenticationError",
    "LLMCompletedEvent",
    "LLMContentRejectedError",
    "LLMError",
    "LLMErrorEvent",
    "LLMErrorKind",
    "LLMEvent",
    "LLMEventType",
    "LLMFinishReason",
    "LLMInvalidRequestError",
    "LLMMessage",
    "LLMProviderCapabilities",
    "LLMProviderUnavailableError",
    "LLMRateLimitedError",
    "LLMRequest",
    "LLMResponse",
    "LLMRole",
    "LLMStartedEvent",
    "LLMTextDeltaEvent",
    "LLMTimeoutError",
    "LLMToolCall",
    "LLMToolCallCompletedEvent",
    "LLMToolCallDeltaEvent",
    "LLMToolCallStartedEvent",
    "LLMToolDefinition",
    "LLMUnknownProviderError",
    "LLMUsage",
    "LLMUsageEvent",
]
