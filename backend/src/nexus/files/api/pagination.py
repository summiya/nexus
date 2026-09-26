"""Opaque HTTP cursor codec for File keyset pagination."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from uuid import UUID

from nexus.errors import ErrorCode, NexusError
from nexus.files.application import FilePageCursor

_CURSOR_VERSION = 1
_INVALID_CURSOR_MESSAGE = "The file cursor is invalid."


def encode_file_cursor(cursor: FilePageCursor) -> str:
    payload = json.dumps(
        {
            "v": _CURSOR_VERSION,
            "created_at": cursor.created_at.isoformat(),
            "public_id": str(cursor.public_id),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def decode_file_cursor(value: str | None) -> FilePageCursor | None:
    if value is None:
        return None
    try:
        padding = "=" * (-len(value) % 4)
        raw = base64.b64decode(
            value + padding,
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or set(payload) != {
            "v",
            "created_at",
            "public_id",
        }:
            raise ValueError
        if payload["v"] != _CURSOR_VERSION:
            raise ValueError
        created_at_value = payload["created_at"]
        public_id_value = payload["public_id"]
        if not isinstance(created_at_value, str) or not isinstance(
            public_id_value, str
        ):
            raise TypeError
        created_at = datetime.fromisoformat(created_at_value)
        public_id = UUID(public_id_value)
        return FilePageCursor(created_at=created_at, public_id=public_id)
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as exc:
        raise NexusError(
            ErrorCode.VALIDATION_ERROR,
            _INVALID_CURSOR_MESSAGE,
        ) from exc


__all__ = ["decode_file_cursor", "encode_file_cursor"]
