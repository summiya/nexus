"""AES-GCM protection for trusted File upload context."""

from __future__ import annotations

import base64
import binascii
import json
import os
from datetime import datetime
from typing import Final, cast
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from nexus.files.domain import UploadContext
from nexus.files.ports import (
    UPLOAD_CONTEXT_MAX_LENGTH,
    UploadContextProtectionError,
    UploadContextProtector,
)

UPLOAD_CONTEXT_KEY_ID: Final = "primary"
_FORMAT_VERSION = "nuc1"
_NONCE_LENGTH = 12
_KEY_LENGTH = 32
_ERROR_MESSAGE = "File upload context protection failed"
_PAYLOAD_FIELDS = frozenset(
    {
        "version",
        "file_public_id",
        "organization_public_id",
        "created_by_user_public_id",
        "storage_key",
        "original_name",
        "mime_type",
        "declared_size_bytes",
        "issued_at",
        "grant_expires_at",
    }
)


class AesGcmUploadContextProtector(UploadContextProtector):
    """Protect upload context with a versioned, authenticated AES-256 envelope."""

    def __init__(self, key: bytes, *, key_id: str = UPLOAD_CONTEXT_KEY_ID) -> None:
        if len(key) != _KEY_LENGTH or key_id != UPLOAD_CONTEXT_KEY_ID:
            raise _protection_error()
        self._cipher = AESGCM(key)
        self._key_id = key_id

    @classmethod
    def from_base64url_key(
        cls,
        encoded_key: str,
        *,
        key_id: str = UPLOAD_CONTEXT_KEY_ID,
    ) -> AesGcmUploadContextProtector:
        """Construct from a URL-safe Base64 encoding of exactly 32 bytes."""

        if not isinstance(encoded_key, str) or not encoded_key:
            raise _protection_error()
        try:
            padding = "=" * (-len(encoded_key) % 4)
            key = base64.b64decode(
                encoded_key + padding,
                altchars=b"-_",
                validate=True,
            )
        except (binascii.Error, ValueError) as exc:
            raise _protection_error() from exc
        return cls(key, key_id=key_id)

    def protect(self, context: UploadContext) -> str:
        payload = json.dumps(
            _context_payload(context),
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        nonce = os.urandom(_NONCE_LENGTH)
        ciphertext = self._cipher.encrypt(nonce, payload, self._associated_data())
        protected = ".".join(
            (
                _FORMAT_VERSION,
                self._key_id,
                _encode_base64url(nonce),
                _encode_base64url(ciphertext),
            )
        )
        if len(protected) > UPLOAD_CONTEXT_MAX_LENGTH:
            raise _protection_error()
        return protected

    def unprotect(self, value: str) -> UploadContext:
        try:
            if (
                not isinstance(value, str)
                or not value
                or len(value) > UPLOAD_CONTEXT_MAX_LENGTH
            ):
                raise ValueError
            format_version, key_id, encoded_nonce, encoded_ciphertext = value.split(".")
            if format_version != _FORMAT_VERSION or key_id != self._key_id:
                raise ValueError
            nonce = _decode_base64url(encoded_nonce)
            ciphertext = _decode_base64url(encoded_ciphertext)
            if len(nonce) != _NONCE_LENGTH:
                raise ValueError
            payload_bytes = self._cipher.decrypt(
                nonce,
                ciphertext,
                self._associated_data(),
            )
            payload = json.loads(payload_bytes.decode("utf-8"))
            return _context_from_payload(payload)
        except (
            InvalidTag,
            UnicodeDecodeError,
            ValueError,
            TypeError,
            KeyError,
            binascii.Error,
        ) as exc:
            raise _protection_error() from exc

    def _associated_data(self) -> bytes:
        return f"{_FORMAT_VERSION}.{self._key_id}".encode("ascii")


def _context_payload(context: UploadContext) -> dict[str, object]:
    return {
        "version": context.version,
        "file_public_id": str(context.file_public_id),
        "organization_public_id": str(context.organization_public_id),
        "created_by_user_public_id": str(context.created_by_user_public_id),
        "storage_key": context.storage_key,
        "original_name": context.original_name,
        "mime_type": context.mime_type,
        "declared_size_bytes": context.declared_size_bytes,
        "issued_at": context.issued_at.isoformat(),
        "grant_expires_at": context.grant_expires_at.isoformat(),
    }


def _context_from_payload(value: object) -> UploadContext:
    if not isinstance(value, dict) or set(value) != _PAYLOAD_FIELDS:
        raise ValueError
    version = value["version"]
    declared_size_bytes = value["declared_size_bytes"]
    string_fields = {
        name: value[name]
        for name in _PAYLOAD_FIELDS
        if name not in {"version", "declared_size_bytes"}
    }
    if not all(isinstance(item, str) for item in string_fields.values()):
        raise TypeError
    return UploadContext(
        version=cast(int, version),
        file_public_id=UUID(cast(str, string_fields["file_public_id"])),
        organization_public_id=UUID(cast(str, string_fields["organization_public_id"])),
        created_by_user_public_id=UUID(
            cast(str, string_fields["created_by_user_public_id"])
        ),
        storage_key=cast(str, string_fields["storage_key"]),
        original_name=cast(str, string_fields["original_name"]),
        mime_type=cast(str, string_fields["mime_type"]),
        declared_size_bytes=cast(int, declared_size_bytes),
        issued_at=datetime.fromisoformat(cast(str, string_fields["issued_at"])),
        grant_expires_at=datetime.fromisoformat(
            cast(str, string_fields["grant_expires_at"])
        ),
    )


def _encode_base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_base64url(value: str) -> bytes:
    if not value:
        raise ValueError
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(
        value + padding,
        altchars=b"-_",
        validate=True,
    )


def _protection_error() -> UploadContextProtectionError:
    return UploadContextProtectionError(_ERROR_MESSAGE)


__all__ = [
    "UPLOAD_CONTEXT_KEY_ID",
    "AesGcmUploadContextProtector",
]
