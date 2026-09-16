"""Canonical user identity normalization rules."""

from __future__ import annotations

import unicodedata


def normalize_email(value: str) -> str:
    """Return the canonical NEXUS representation of an email identifier.

    Full syntactic email validation belongs at the API/application boundary. This
    helper owns only canonicalization so persistence and lookup paths use the
    same stable representation.
    """

    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    if not normalized:
        raise ValueError("email must not be empty")
    return normalized
