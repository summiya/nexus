"""Conversation title derivation rules."""

AUTO_CONVERSATION_TITLE_MAX_LENGTH = 80


def conversation_title_from_message(content: str) -> str:
    """Build a compact deterministic title from one user message."""

    normalized = " ".join(content.split())
    if not normalized:
        raise ValueError("conversation title source must not be blank")
    if len(normalized) <= AUTO_CONVERSATION_TITLE_MAX_LENGTH:
        return normalized

    return f"{normalized[: AUTO_CONVERSATION_TITLE_MAX_LENGTH - 1].rstrip()}…"


__all__ = [
    "AUTO_CONVERSATION_TITLE_MAX_LENGTH",
    "conversation_title_from_message",
]
