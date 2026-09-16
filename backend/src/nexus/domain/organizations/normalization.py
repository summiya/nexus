"""Canonical organization normalization rules."""

from __future__ import annotations

import re
import unicodedata

_SLUG_SEPARATOR_RE = re.compile(r"[^a-z0-9]+")


def normalize_slug(value: str) -> str:
    """Return a stable, URL-safe organization slug."""
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    slug = _SLUG_SEPARATOR_RE.sub("-", normalized).strip("-")
    if not slug:
        raise ValueError("organization slug must not be empty")
    return slug
