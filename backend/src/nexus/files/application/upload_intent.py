"""Validation and storage identity policy for a prospective File upload."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from uuid import uuid4

from nexus.files.domain import MAX_MIME_TYPE_LENGTH, MAX_ORIGINAL_NAME_LENGTH

_DEFAULT_MIME_TYPE = "application/octet-stream"
_MAX_MIME_RESTRICTED_NAME_LENGTH = 127
_DISALLOWED_FILENAME_BIDI_CLASSES = frozenset(
    {"LRE", "RLE", "LRO", "RLO", "PDF", "LRI", "RLI", "FSI", "PDI"}
)
_MIME_TYPE_PATTERN = re.compile(
    r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$",
    re.ASCII,
)


class UploadIntentValidationError(ValueError):
    """Raised when untrusted upload metadata violates the upload policy."""


@dataclass(frozen=True)
class ValidatedUploadIntent:
    """Normalized metadata and Nexus-owned identity for a prospective upload."""

    original_name: str
    mime_type: str
    declared_size_bytes: int
    storage_key: str


@dataclass(frozen=True)
class UploadIntentPolicy:
    """Validate declared upload metadata and generate an opaque storage key."""

    max_size_bytes: int

    def __post_init__(self) -> None:
        if isinstance(self.max_size_bytes, bool) or not isinstance(
            self.max_size_bytes,
            int,
        ):
            raise TypeError("max_size_bytes must be a positive integer")
        if self.max_size_bytes <= 0:
            raise ValueError("max_size_bytes must be a positive integer")

    def prepare(
        self,
        *,
        original_name: str,
        mime_type: str | None,
        size_bytes: int,
    ) -> ValidatedUploadIntent:
        """Return normalized metadata after validating one upload declaration."""

        normalized_name = _normalize_original_name(original_name)
        normalized_mime_type = _normalize_mime_type(mime_type)
        declared_size_bytes = self._validate_declared_size(size_bytes)

        return ValidatedUploadIntent(
            original_name=normalized_name,
            mime_type=normalized_mime_type,
            declared_size_bytes=declared_size_bytes,
            storage_key=f"files/{uuid4().hex}",
        )

    def _validate_declared_size(self, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise UploadIntentValidationError("File size is invalid.")
        if value > self.max_size_bytes:
            raise UploadIntentValidationError("File exceeds the upload-size limit.")
        return value


def _normalize_original_name(value: str) -> str:
    if not isinstance(value, str):
        raise UploadIntentValidationError("File name is invalid.")
    if "/" in value or "\\" in value or _contains_unsafe_filename_character(value):
        raise UploadIntentValidationError("File name is invalid.")

    normalized = value.strip()
    if not normalized or len(normalized) > MAX_ORIGINAL_NAME_LENGTH:
        raise UploadIntentValidationError("File name is invalid.")
    return normalized


def _normalize_mime_type(value: str | None) -> str:
    if value is None:
        return _DEFAULT_MIME_TYPE
    if not isinstance(value, str) or _contains_control_character(value):
        raise UploadIntentValidationError("MIME type is invalid.")

    normalized = value.strip().lower()
    if not normalized:
        return _DEFAULT_MIME_TYPE
    if (
        len(normalized) > MAX_MIME_TYPE_LENGTH
        or _MIME_TYPE_PATTERN.fullmatch(normalized) is None
    ):
        raise UploadIntentValidationError("MIME type is invalid.")

    type_name, subtype_name = normalized.split("/", maxsplit=1)
    if (
        len(type_name) > _MAX_MIME_RESTRICTED_NAME_LENGTH
        or len(subtype_name) > _MAX_MIME_RESTRICTED_NAME_LENGTH
    ):
        raise UploadIntentValidationError("MIME type is invalid.")
    return normalized


def _contains_control_character(value: str) -> bool:
    return any(unicodedata.category(character) == "Cc" for character in value)


def _contains_unsafe_filename_character(value: str) -> bool:
    return any(
        unicodedata.category(character) == "Cc"
        or unicodedata.bidirectional(character) in _DISALLOWED_FILENAME_BIDI_CLASSES
        for character in value
    )
