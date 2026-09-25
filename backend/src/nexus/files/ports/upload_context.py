"""Protection boundary for trusted File upload context."""

from __future__ import annotations

from typing import Protocol

from nexus.files.domain import UploadContext

UPLOAD_CONTEXT_MAX_LENGTH = 4096


class UploadContextProtectionError(Exception):
    """A File upload context could not be protected or authenticated."""


class UploadContextProtector(Protocol):
    """Protect and authenticate one provider-neutral File upload context."""

    def protect(self, context: UploadContext) -> str: ...

    def unprotect(self, value: str) -> UploadContext: ...


__all__ = [
    "UPLOAD_CONTEXT_MAX_LENGTH",
    "UploadContextProtectionError",
    "UploadContextProtector",
]
