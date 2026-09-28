from __future__ import annotations

import asyncio
from dataclasses import replace
from uuid import UUID, uuid4

import pytest

import nexus.model_providers.application.providers as provider_application
from nexus.errors import ErrorCode, NexusError
from nexus.model_providers.application import (
    ListProviderCatalog,
    ManageModelProviders,
    ReadModelProviders,
)
from nexus.model_providers.domain import (
    ConfiguredProvider,
    CredentialReference,
    DefaultModelSelection,
    OpenAICompatibleSettings,
    OpenAISettings,
    OrganizationModelProviderConfiguration,
    OrganizationProviderId,
    ProviderCredentialSecret,
    ProviderType,
)
from nexus.model_providers.ports import (
    ModelProviderConflictError,
    ModelProviderDeleteRestrictedError,
    ProviderUpdateResult,
)


class FakePermissionChecker:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.calls: list[tuple[UUID, UUID, str]] = []

    async def has_permission(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        permission_key: str,
    ) -> bool:
        self.calls.append((organization_public_id, user_public_id, permission_key))
        return self.allowed


class FakePersistence:
    def __init__(self, provider: ConfiguredProvider | None = None) -> None:
        self.provider = provider
        self.set_error: Exception | None = None
        self.delete_error: Exception | None = None
        self.set_calls: list[
            tuple[CredentialReference | None, CredentialReference | None]
        ] = []

    async def load_configuration(
        self, *, organization_public_id: UUID
    ) -> OrganizationModelProviderConfiguration | None:
        providers = () if self.provider is None else (self.provider,)
        return OrganizationModelProviderConfiguration(
            organization_public_id=organization_public_id,
            providers=providers,
            defaults=DefaultModelSelection(),
        )

    async def create_provider(self, provider: ConfiguredProvider) -> None:
        self.provider = provider

    async def update_provider(
        self, provider: ConfiguredProvider
    ) -> ProviderUpdateResult:
        assert self.provider is not None
        old_reference = self.provider.credential_reference
        old_url = _url(self.provider)
        new_url = _url(provider)
        updated = replace(
            provider,
            credential_reference=(None if old_url != new_url else old_reference),
        )
        self.provider = updated
        return ProviderUpdateResult(
            provider=updated,
            cleared_credential_reference=(
                old_reference if old_url != new_url else None
            ),
        )

    async def set_provider_credential_reference(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        expected_credential_reference: CredentialReference | None,
        credential_reference: CredentialReference | None,
    ) -> ConfiguredProvider:
        self.set_calls.append((expected_credential_reference, credential_reference))
        if self.set_error is not None:
            raise self.set_error
        assert self.provider is not None
        assert self.provider.provider_id == provider_id
        self.provider = replace(
            self.provider,
            credential_reference=credential_reference,
        )
        return self.provider

    async def delete_provider(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
    ) -> ConfiguredProvider:
        if self.delete_error is not None:
            raise self.delete_error
        assert self.provider is not None
        deleted = self.provider
        self.provider = None
        return deleted


class FakeCredentialStore:
    def __init__(self) -> None:
        self.put_calls: list[tuple[CredentialReference, str]] = []
        self.delete_calls: list[CredentialReference] = []
        self.fail_delete = False
        self.fail_put = False

    async def put(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        credential_reference: CredentialReference,
        secret: ProviderCredentialSecret,
    ) -> None:
        if self.fail_put:
            from nexus.model_providers.ports import CredentialStoreError

            raise CredentialStoreError("must not leak")
        self.put_calls.append((credential_reference, secret.reveal()))

    async def delete(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        credential_reference: CredentialReference,
    ) -> None:
        self.delete_calls.append(credential_reference)
        if self.fail_delete:
            from nexus.model_providers.ports import CredentialStoreError

            raise CredentialStoreError("must not leak")


def _provider(
    organization_id: UUID,
    *,
    reference: CredentialReference | None = None,
    base_url: str | None = None,
) -> ConfiguredProvider:
    return ConfiguredProvider(
        organization_public_id=organization_id,
        provider_id=OrganizationProviderId(uuid4()),
        provider_type=(
            ProviderType.OPENAI_COMPATIBLE
            if base_url is not None
            else ProviderType.OPENAI
        ),
        display_name="Provider",
        settings=(
            OpenAICompatibleSettings(base_url=base_url)
            if base_url is not None
            else OpenAISettings()
        ),
        enabled=True,
        credential_reference=reference,
    )


def _manager(
    persistence: FakePersistence,
    store: FakeCredentialStore | None,
) -> ManageModelProviders:
    return ManageModelProviders(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=FakePermissionChecker(),
        credential_store=store,  # type: ignore[arg-type]
    )


def _url(provider: ConfiguredProvider) -> str | None:
    settings = provider.settings
    return settings.base_url if isinstance(settings, OpenAICompatibleSettings) else None


def test_catalog_is_backend_owned_and_requires_read_permission() -> None:
    organization_id = uuid4()
    user_id = uuid4()
    checker = FakePermissionChecker()
    service = ListProviderCatalog(permission_checker=checker)

    items = asyncio.run(
        service.execute(
            organization_public_id=organization_id,
            user_public_id=user_id,
        )
    )

    assert [item.provider_type for item in items] == list(ProviderType)
    assert checker.calls == [(organization_id, user_id, "model_providers.read")]


def test_read_provider_uses_trusted_organization_scope_and_hides_unknown_id() -> None:
    organization_id = uuid4()
    user_id = uuid4()
    provider = _provider(organization_id)
    persistence = FakePersistence(provider)
    service = ReadModelProviders(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=FakePermissionChecker(),
    )

    assert (
        asyncio.run(
            service.get(
                organization_public_id=organization_id,
                user_public_id=user_id,
                provider_public_id=provider.provider_id.value,
            )
        )
        == provider
    )
    with pytest.raises(NexusError) as captured:
        asyncio.run(
            service.get(
                organization_public_id=organization_id,
                user_public_id=user_id,
                provider_public_id=uuid4(),
            )
        )
    assert captured.value.code is ErrorCode.NOT_FOUND


def test_create_and_enable_delegate_only_after_manage_authorization() -> None:
    organization_id = uuid4()
    user_id = uuid4()
    permission = FakePermissionChecker()
    persistence = FakePersistence()
    manager = ManageModelProviders(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=permission,
        credential_store=None,
    )

    created = asyncio.run(
        manager.create(
            organization_public_id=organization_id,
            user_public_id=user_id,
            provider_type=ProviderType.OPENAI,
            display_name="OpenAI",
            settings={},
            enabled=True,
        )
    )
    disabled = asyncio.run(
        manager.set_enabled(
            organization_public_id=organization_id,
            user_public_id=user_id,
            provider_public_id=created.provider_id.value,
            enabled=False,
        )
    )

    assert disabled.enabled is False
    assert permission.calls == [
        (organization_id, user_id, "model_providers.manage"),
        (organization_id, user_id, "model_providers.manage"),
    ]


def test_manage_permission_denial_prevents_mutation() -> None:
    organization_id = uuid4()
    persistence = FakePersistence()
    manager = ManageModelProviders(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=FakePermissionChecker(allowed=False),
        credential_store=None,
    )

    with pytest.raises(NexusError) as captured:
        asyncio.run(
            manager.create(
                organization_public_id=organization_id,
                user_public_id=uuid4(),
                provider_type=ProviderType.OPENAI,
                display_name="OpenAI",
                settings={},
                enabled=True,
            )
        )

    assert captured.value.code is ErrorCode.FORBIDDEN
    assert persistence.provider is None


def test_credential_replacement_uses_new_reference_and_deletes_old_secret() -> None:
    organization_id = uuid4()
    user_id = uuid4()
    old_reference = CredentialReference(uuid4())
    provider = _provider(organization_id, reference=old_reference)
    persistence = FakePersistence(provider)
    store = FakeCredentialStore()

    updated = asyncio.run(
        _manager(persistence, store).set_credential(
            organization_public_id=organization_id,
            user_public_id=user_id,
            provider_public_id=provider.provider_id.value,
            secret=ProviderCredentialSecret("new-secret"),
        )
    )

    new_reference = store.put_calls[0][0]
    assert new_reference != old_reference
    assert persistence.set_calls == [(old_reference, new_reference)]
    assert store.delete_calls == [old_reference]
    assert updated.credential_reference == new_reference


def test_stale_credential_switch_compensates_new_secret() -> None:
    organization_id = uuid4()
    provider = _provider(
        organization_id,
        reference=CredentialReference(uuid4()),
    )
    persistence = FakePersistence(provider)
    persistence.set_error = ModelProviderConflictError("stale")
    store = FakeCredentialStore()

    with pytest.raises(NexusError) as captured:
        asyncio.run(
            _manager(persistence, store).set_credential(
                organization_public_id=organization_id,
                user_public_id=uuid4(),
                provider_public_id=provider.provider_id.value,
                secret=ProviderCredentialSecret("new-secret"),
            )
        )

    assert captured.value.code is ErrorCode.CONFLICT
    assert store.delete_calls == [store.put_calls[0][0]]


def test_credential_store_failure_leaves_database_reference_unchanged() -> None:
    organization_id = uuid4()
    original_reference = CredentialReference(uuid4())
    provider = _provider(organization_id, reference=original_reference)
    persistence = FakePersistence(provider)
    store = FakeCredentialStore()
    store.fail_put = True

    with pytest.raises(NexusError) as captured:
        asyncio.run(
            _manager(persistence, store).set_credential(
                organization_public_id=organization_id,
                user_public_id=uuid4(),
                provider_public_id=provider.provider_id.value,
                secret=ProviderCredentialSecret("must-not-leak"),
            )
        )

    assert captured.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert persistence.provider is not None
    assert persistence.provider.credential_reference == original_reference
    assert persistence.set_calls == []


def test_provider_url_change_clears_credential_but_display_edit_retains_it() -> None:
    organization_id = uuid4()
    user_id = uuid4()
    reference = CredentialReference(uuid4())
    provider = _provider(
        organization_id,
        reference=reference,
        base_url="https://first.example.com",
    )
    persistence = FakePersistence(provider)
    store = FakeCredentialStore()
    manager = _manager(persistence, store)

    display_only = asyncio.run(
        manager.update(
            organization_public_id=organization_id,
            user_public_id=user_id,
            provider_public_id=provider.provider_id.value,
            display_name="Renamed",
            settings={"base_url": "https://first.example.com"},
        )
    )
    assert display_only.credential_reference == reference
    assert store.delete_calls == []

    changed = asyncio.run(
        manager.update(
            organization_public_id=organization_id,
            user_public_id=user_id,
            provider_public_id=provider.provider_id.value,
            display_name="Renamed",
            settings={"base_url": "https://second.example.com"},
        )
    )
    assert changed.credential_reference is None
    assert store.delete_calls == [reference]


def test_disabling_provider_retains_credential() -> None:
    organization_id = uuid4()
    reference = CredentialReference(uuid4())
    provider = _provider(organization_id, reference=reference)
    persistence = FakePersistence(provider)
    store = FakeCredentialStore()

    disabled = asyncio.run(
        _manager(persistence, store).set_enabled(
            organization_public_id=organization_id,
            user_public_id=uuid4(),
            provider_public_id=provider.provider_id.value,
            enabled=False,
        )
    )

    assert disabled.enabled is False
    assert disabled.credential_reference == reference
    assert store.delete_calls == []


def test_delete_restriction_does_not_delete_credential() -> None:
    organization_id = uuid4()
    provider = _provider(
        organization_id,
        reference=CredentialReference(uuid4()),
    )
    persistence = FakePersistence(provider)
    persistence.delete_error = ModelProviderDeleteRestrictedError("restricted")
    store = FakeCredentialStore()

    with pytest.raises(NexusError) as captured:
        asyncio.run(
            _manager(persistence, store).delete(
                organization_public_id=organization_id,
                user_public_id=uuid4(),
                provider_public_id=provider.provider_id.value,
            )
        )

    assert captured.value.code is ErrorCode.CONFLICT
    assert store.delete_calls == []


def test_delete_cleanup_failure_logs_only_safe_operational_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid4()
    user_id = uuid4()
    reference = CredentialReference(uuid4())
    provider = _provider(organization_id, reference=reference)
    persistence = FakePersistence(provider)
    store = FakeCredentialStore()
    store.fail_delete = True
    events: list[tuple[str, dict[str, object]]] = []

    class FakeLogger:
        def info(self, event: str, **values: object) -> None:
            events.append((event, values))

        def warning(self, event: str, **values: object) -> None:
            events.append((event, values))

    monkeypatch.setattr(provider_application, "logger", FakeLogger())

    asyncio.run(
        _manager(persistence, store).delete(
            organization_public_id=organization_id,
            user_public_id=user_id,
            provider_public_id=provider.provider_id.value,
        )
    )

    cleanup = next(
        values for event, values in events if event.endswith("cleanup_failed")
    )
    assert cleanup["organization_public_id"] == str(organization_id)
    assert cleanup["actor_user_public_id"] == str(user_id)
    assert cleanup["provider_public_id"] == str(provider.provider_id.value)
    assert str(cleanup["orphan_storage_name"]).startswith("npc-v1-")
    serialized = repr(events)
    assert "must not leak" not in serialized
    assert str(reference.value) not in serialized
