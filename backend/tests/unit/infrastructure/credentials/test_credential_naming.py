import re
from uuid import uuid4

from nexus.model_providers.domain import CredentialReference, OrganizationProviderId
from nexus.model_providers.ports import credential_storage_name


def test_credential_storage_name_is_deterministic_opaque_and_key_vault_safe() -> None:
    organization_public_id = uuid4()
    provider_id = OrganizationProviderId(uuid4())
    reference = CredentialReference(uuid4())

    first = credential_storage_name(
        organization_public_id=organization_public_id,
        provider_id=provider_id,
        credential_reference=reference,
    )
    second = credential_storage_name(
        organization_public_id=organization_public_id,
        provider_id=provider_id,
        credential_reference=reference,
    )

    assert first == second
    assert len(first) == 71
    assert len(first) <= 127
    assert re.fullmatch(r"[0-9a-zA-Z-]+", first)
    assert str(organization_public_id) not in first
    assert str(provider_id.value) not in first
    assert reference.value.hex not in first


def test_each_scope_component_changes_the_storage_name() -> None:
    organization_public_id = uuid4()
    provider_id = OrganizationProviderId(uuid4())
    reference = CredentialReference(uuid4())
    base = credential_storage_name(
        organization_public_id=organization_public_id,
        provider_id=provider_id,
        credential_reference=reference,
    )

    assert base != credential_storage_name(
        organization_public_id=uuid4(),
        provider_id=provider_id,
        credential_reference=reference,
    )
    assert base != credential_storage_name(
        organization_public_id=organization_public_id,
        provider_id=OrganizationProviderId(uuid4()),
        credential_reference=reference,
    )
    assert base != credential_storage_name(
        organization_public_id=organization_public_id,
        provider_id=provider_id,
        credential_reference=CredentialReference(uuid4()),
    )
