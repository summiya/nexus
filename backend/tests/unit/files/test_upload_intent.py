from __future__ import annotations

import re
from dataclasses import FrozenInstanceError

import pytest

from nexus.files.application import (
    UploadIntentPolicy,
    UploadIntentValidationError,
    ValidatedUploadIntent,
)
from nexus.files.domain import MAX_MIME_TYPE_LENGTH, MAX_ORIGINAL_NAME_LENGTH

MAX_SIZE_BYTES = 52_428_800
STORAGE_KEY_PATTERN = re.compile(r"^files/[0-9a-f]{32}$", re.ASCII)


@pytest.fixture
def policy() -> UploadIntentPolicy:
    return UploadIntentPolicy(max_size_bytes=MAX_SIZE_BYTES)


def test_prepare_normalizes_metadata_and_marks_size_as_declared(
    policy: UploadIntentPolicy,
) -> None:
    intent = policy.prepare(
        original_name="  Quarterly Report.PDF  ",
        mime_type="  APPLICATION/PDF  ",
        size_bytes=42,
    )

    assert intent == ValidatedUploadIntent(
        original_name="Quarterly Report.PDF",
        mime_type="application/pdf",
        declared_size_bytes=42,
        storage_key=intent.storage_key,
    )
    assert intent.declared_size_bytes == 42
    assert not hasattr(intent, "size_bytes")


@pytest.mark.parametrize(
    "original_name",
    [
        "résumé 2026.pdf",
        "archive.tar.gz",
        ".contract",
        "文件 版本一.pdf",
        "تقرير 2026.pdf",
        "report\u200cfinal.pdf",
    ],
)
def test_prepare_preserves_supported_unicode_and_filename_forms(
    policy: UploadIntentPolicy,
    original_name: str,
) -> None:
    intent = policy.prepare(
        original_name=original_name,
        mime_type="application/pdf",
        size_bytes=1,
    )

    assert intent.original_name == original_name


@pytest.mark.parametrize(
    "original_name",
    [
        "",
        "   ",
        "folder/report.pdf",
        r"folder\report.pdf",
        "bad\x00name.pdf",
        "bad\nname.pdf",
        "bad\rname.pdf",
        "bad\tname.pdf",
        "bad\x85name.pdf",
        "a" * (MAX_ORIGINAL_NAME_LENGTH + 1),
    ],
)
def test_prepare_rejects_invalid_filename(
    policy: UploadIntentPolicy,
    original_name: str,
) -> None:
    with pytest.raises(
        UploadIntentValidationError,
        match=r"^File name is invalid\.$",
    ):
        policy.prepare(
            original_name=original_name,
            mime_type="application/pdf",
            size_bytes=1,
        )


@pytest.mark.parametrize(
    "bidi_control",
    [
        "\u202a",  # LRE
        "\u202b",  # RLE
        "\u202d",  # LRO
        "\u202e",  # RLO
        "\u202c",  # PDF
        "\u2066",  # LRI
        "\u2067",  # RLI
        "\u2068",  # FSI
        "\u2069",  # PDI
    ],
)
def test_prepare_rejects_explicit_filename_bidi_controls(
    policy: UploadIntentPolicy,
    bidi_control: str,
) -> None:
    with pytest.raises(
        UploadIntentValidationError,
        match=r"^File name is invalid\.$",
    ):
        policy.prepare(
            original_name=f"invoice{bidi_control}fdp.exe",
            mime_type="application/octet-stream",
            size_bytes=1,
        )


def test_prepare_accepts_filename_at_domain_limit(
    policy: UploadIntentPolicy,
) -> None:
    intent = policy.prepare(
        original_name="a" * MAX_ORIGINAL_NAME_LENGTH,
        mime_type="application/pdf",
        size_bytes=1,
    )

    assert len(intent.original_name) == MAX_ORIGINAL_NAME_LENGTH


def test_prepare_rejects_non_string_filename(policy: UploadIntentPolicy) -> None:
    with pytest.raises(UploadIntentValidationError, match="File name is invalid"):
        policy.prepare(  # type: ignore[arg-type]
            original_name=123,
            mime_type="application/pdf",
            size_bytes=1,
        )


@pytest.mark.parametrize("mime_type", [None, "", "   ", "\u00a0"])
def test_prepare_defaults_absent_or_blank_mime_type(
    policy: UploadIntentPolicy,
    mime_type: str | None,
) -> None:
    intent = policy.prepare(
        original_name="report.bin",
        mime_type=mime_type,
        size_bytes=1,
    )

    assert intent.mime_type == "application/octet-stream"


@pytest.mark.parametrize(
    ("mime_type", "expected"),
    [
        ("TEXT/PLAIN", "text/plain"),
        (
            " application/vnd.nexus.document+json ",
            "application/vnd.nexus.document+json",
        ),
        ("image/svg+xml", "image/svg+xml"),
        ("application/x.custom_type", "application/x.custom_type"),
    ],
)
def test_prepare_normalizes_supported_bare_mime_types(
    policy: UploadIntentPolicy,
    mime_type: str,
    expected: str,
) -> None:
    intent = policy.prepare(
        original_name="report",
        mime_type=mime_type,
        size_bytes=1,
    )

    assert intent.mime_type == expected


def test_prepare_accepts_mime_type_components_at_restricted_name_limit(
    policy: UploadIntentPolicy,
) -> None:
    mime_type = f"{'a' * 127}/{'b' * 127}"

    intent = policy.prepare(
        original_name="report",
        mime_type=mime_type,
        size_bytes=1,
    )

    assert intent.mime_type == mime_type


@pytest.mark.parametrize(
    "mime_type",
    [
        f"{'a' * 128}/b",
        f"a/{'b' * 128}",
    ],
)
def test_prepare_rejects_mime_type_component_above_restricted_name_limit(
    policy: UploadIntentPolicy,
    mime_type: str,
) -> None:
    with pytest.raises(
        UploadIntentValidationError,
        match=r"^MIME type is invalid\.$",
    ):
        policy.prepare(
            original_name="report",
            mime_type=mime_type,
            size_bytes=1,
        )


@pytest.mark.parametrize(
    "mime_type",
    [
        "text",
        "/plain",
        "text/",
        "text/*",
        "*/plain",
        "text/plain; charset=utf-8",
        "text /plain",
        "text/ plain",
        "text//plain",
        "-text/plain",
        "text/-plain",
        "text/pla(in",
        "text\n/plain",
        "a" * (MAX_MIME_TYPE_LENGTH + 1),
    ],
)
def test_prepare_rejects_invalid_mime_type(
    policy: UploadIntentPolicy,
    mime_type: str,
) -> None:
    with pytest.raises(
        UploadIntentValidationError,
        match=r"^MIME type is invalid\.$",
    ):
        policy.prepare(
            original_name="report",
            mime_type=mime_type,
            size_bytes=1,
        )


def test_prepare_rejects_non_string_mime_type(policy: UploadIntentPolicy) -> None:
    with pytest.raises(UploadIntentValidationError, match="MIME type is invalid"):
        policy.prepare(  # type: ignore[arg-type]
            original_name="report",
            mime_type=42,
            size_bytes=1,
        )


@pytest.mark.parametrize("size_bytes", [0, 1, MAX_SIZE_BYTES])
def test_prepare_accepts_size_boundaries(
    policy: UploadIntentPolicy,
    size_bytes: int,
) -> None:
    intent = policy.prepare(
        original_name="report.pdf",
        mime_type="application/pdf",
        size_bytes=size_bytes,
    )

    assert intent.declared_size_bytes == size_bytes


@pytest.mark.parametrize("size_bytes", [-1, 1.5, "1", None, True, False])
def test_prepare_rejects_invalid_declared_size(
    policy: UploadIntentPolicy,
    size_bytes: object,
) -> None:
    with pytest.raises(
        UploadIntentValidationError,
        match=r"^File size is invalid\.$",
    ):
        policy.prepare(
            original_name="report.pdf",
            mime_type="application/pdf",
            size_bytes=size_bytes,  # type: ignore[arg-type]
        )


def test_prepare_rejects_size_above_configured_limit(
    policy: UploadIntentPolicy,
) -> None:
    with pytest.raises(
        UploadIntentValidationError,
        match=r"^File exceeds the upload-size limit\.$",
    ):
        policy.prepare(
            original_name="report.pdf",
            mime_type="application/pdf",
            size_bytes=MAX_SIZE_BYTES + 1,
        )


@pytest.mark.parametrize("max_size_bytes", [0, -1])
def test_policy_requires_positive_maximum(max_size_bytes: int) -> None:
    with pytest.raises(ValueError, match="max_size_bytes must be a positive integer"):
        UploadIntentPolicy(max_size_bytes=max_size_bytes)


@pytest.mark.parametrize("max_size_bytes", [True, 1.5, "10"])
def test_policy_requires_integer_maximum(max_size_bytes: object) -> None:
    with pytest.raises(TypeError, match="max_size_bytes must be a positive integer"):
        UploadIntentPolicy(max_size_bytes=max_size_bytes)  # type: ignore[arg-type]


def test_prepare_generates_canonical_portable_unique_storage_keys(
    policy: UploadIntentPolicy,
) -> None:
    first = policy.prepare(
        original_name="sensitive-report.pdf",
        mime_type="application/pdf",
        size_bytes=1,
    )
    second = policy.prepare(
        original_name="sensitive-report.pdf",
        mime_type="application/pdf",
        size_bytes=1,
    )

    assert STORAGE_KEY_PATTERN.fullmatch(first.storage_key) is not None
    assert len(first.storage_key) == 38
    assert first.storage_key != second.storage_key
    assert "sensitive-report" not in first.storage_key
    assert ".pdf" not in first.storage_key


def test_validated_intent_is_immutable(policy: UploadIntentPolicy) -> None:
    intent = policy.prepare(
        original_name="report.pdf",
        mime_type="application/pdf",
        size_bytes=1,
    )

    with pytest.raises(FrozenInstanceError):
        intent.original_name = "changed.pdf"  # type: ignore[misc]


def test_validation_errors_do_not_echo_submitted_metadata(
    policy: UploadIntentPolicy,
) -> None:
    unsafe_name = "private/customer-name/secret.pdf"

    with pytest.raises(UploadIntentValidationError) as error:
        policy.prepare(
            original_name=unsafe_name,
            mime_type="application/pdf",
            size_bytes=1,
        )

    assert unsafe_name not in str(error.value)
