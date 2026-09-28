import pytest

from nexus.model_providers.domain import ProviderCredentialSecret
from nexus.model_providers.ports import (
    CredentialNotFoundError,
    CredentialStoreConflictError,
    CredentialStoreError,
)


def test_provider_credential_secret_requires_explicit_reveal_and_redacts() -> None:
    plaintext = "provider-key-secret-value"
    secret = ProviderCredentialSecret(plaintext)

    assert secret.reveal() == plaintext
    assert str(secret) == "<redacted>"
    assert repr(secret) == "ProviderCredentialSecret(<redacted>)"
    assert plaintext not in str(secret)
    assert plaintext not in repr(secret)


def test_credential_store_errors_are_provider_neutral() -> None:
    assert issubclass(CredentialNotFoundError, CredentialStoreError)
    assert issubclass(CredentialStoreConflictError, CredentialStoreError)


@pytest.mark.parametrize("value", ["", "   "])
def test_provider_credential_secret_rejects_blank_values_safely(value: str) -> None:
    with pytest.raises(ValueError, match="Provider credential secret is invalid"):
        ProviderCredentialSecret(value)
