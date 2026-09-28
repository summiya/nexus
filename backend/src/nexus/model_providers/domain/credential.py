"""Secure model-provider credential value contracts."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True, repr=False)
class ProviderCredentialSecret:
    """A credential whose plaintext requires an explicit reveal operation."""

    _value: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self._value, str) or not self._value.strip():
            raise ValueError("Provider credential secret is invalid.")

    def reveal(self) -> str:
        """Return the exact credential plaintext for a trusted adapter operation."""

        return self._value

    def __str__(self) -> str:
        return "<redacted>"

    def __repr__(self) -> str:
        return "ProviderCredentialSecret(<redacted>)"
