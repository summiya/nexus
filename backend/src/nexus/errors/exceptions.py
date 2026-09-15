from collections.abc import Mapping
from typing import Any

from nexus.errors.codes import ERROR_STATUS_CODES, ErrorCode


class NexusError(Exception):
    """Framework-independent application error."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details) if details is not None else None
        self.retryable = retryable

    @property
    def status_code(self) -> int:
        """Return the canonical HTTP status associated with this error code."""
        return ERROR_STATUS_CODES[self.code]
