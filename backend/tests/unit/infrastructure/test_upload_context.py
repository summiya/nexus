from __future__ import annotations

import base64
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from nexus.files.domain import UPLOAD_CONTEXT_VERSION, UploadContext
from nexus.files.ports import (
    UPLOAD_CONTEXT_MAX_LENGTH,
    UploadContextProtectionError,
)
from nexus.infrastructure.upload_context import AesGcmUploadContextProtector

KEY = b"nexus-development-upload-key-001"
OTHER_KEY = b"nexus-development-upload-key-002"
ENCODED_KEY = base64.urlsafe_b64encode(KEY).decode("ascii").rstrip("=")
ISSUED_AT = datetime(2026, 9, 25, 12, tzinfo=UTC)


def _context(**changes: object) -> UploadContext:
    context = UploadContext(
        version=UPLOAD_CONTEXT_VERSION,
        file_public_id=uuid4(),
        organization_public_id=uuid4(),
        created_by_user_public_id=uuid4(),
        storage_key=f"files/{uuid4().hex}",
        original_name="confidential-report.pdf",
        mime_type="application/pdf",
        declared_size_bytes=42,
        issued_at=ISSUED_AT,
        grant_expires_at=ISSUED_AT + timedelta(minutes=10),
    )
    return replace(context, **changes)


def _protector(key: bytes = KEY) -> AesGcmUploadContextProtector:
    return AesGcmUploadContextProtector(key)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _token_for_payload(payload: dict[str, object]) -> str:
    nonce = b"0" * 12
    ciphertext = AESGCM(KEY).encrypt(
        nonce,
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(),
        b"nuc1.primary",
    )
    return f"nuc1.primary.{_encode(nonce)}.{_encode(ciphertext)}"


def _payload(context: UploadContext) -> dict[str, object]:
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


def test_aes_gcm_context_round_trip_preserves_values() -> None:
    context = _context()
    protector = AesGcmUploadContextProtector.from_base64url_key(ENCODED_KEY)

    protected = protector.protect(context)

    assert protected.startswith("nuc1.primary.")
    assert protector.unprotect(protected) == context


def test_protected_context_hides_plaintext_and_fits_metadata_budget() -> None:
    context = _context(original_name="文" * 255, mime_type="y" * 255)

    protected = _protector().protect(context)

    assert len(protected) < UPLOAD_CONTEXT_MAX_LENGTH
    assert context.original_name not in protected
    assert str(context.file_public_id) not in protected
    assert context.storage_key not in protected


@pytest.mark.parametrize("mutation", ["ciphertext", "key_id", "format"])
def test_tampered_or_unknown_envelope_is_rejected_safely(mutation: str) -> None:
    protected = _protector().protect(_context())
    format_version, key_id, nonce, ciphertext = protected.split(".")
    if mutation == "ciphertext":
        ciphertext = ("A" if ciphertext[0] != "A" else "B") + ciphertext[1:]
    elif mutation == "key_id":
        key_id = "retired"
    else:
        format_version = "nuc2"
    tampered = f"{format_version}.{key_id}.{nonce}.{ciphertext}"

    with pytest.raises(UploadContextProtectionError) as captured:
        _protector().unprotect(tampered)

    assert str(captured.value) == "File upload context protection failed"
    assert "retired" not in str(captured.value)
    assert tampered not in str(captured.value)


def test_wrong_key_is_rejected_with_the_same_safe_error() -> None:
    protected = _protector().protect(_context())

    with pytest.raises(
        UploadContextProtectionError,
        match="^File upload context protection failed$",
    ):
        _protector(OTHER_KEY).unprotect(protected)


@pytest.mark.parametrize("value", ["", "invalid", "nuc1.primary.bad.bad"])
def test_malformed_value_is_rejected_safely(value: str) -> None:
    with pytest.raises(
        UploadContextProtectionError,
        match="^File upload context protection failed$",
    ):
        _protector().unprotect(value)


def test_authenticated_payload_with_unknown_schema_version_is_rejected() -> None:
    payload = _payload(_context())
    payload["version"] = 2

    with pytest.raises(
        UploadContextProtectionError,
        match="^File upload context protection failed$",
    ):
        _protector().unprotect(_token_for_payload(payload))


def test_unprotect_does_not_reject_context_after_grant_expiration() -> None:
    expired = _context(
        issued_at=datetime(2020, 1, 1, tzinfo=UTC),
        grant_expires_at=datetime(2020, 1, 1, tzinfo=UTC) + timedelta(minutes=1),
    )

    assert _protector().unprotect(_protector().protect(expired)) == expired


@pytest.mark.parametrize("encoded_key", ["", "not-base64!", "dG9vLXNob3J0"])
def test_constructor_rejects_invalid_key_without_exposing_it(
    encoded_key: str,
) -> None:
    with pytest.raises(UploadContextProtectionError) as captured:
        AesGcmUploadContextProtector.from_base64url_key(encoded_key)

    assert str(captured.value) == "File upload context protection failed"
    if encoded_key:
        assert encoded_key not in str(captured.value)
