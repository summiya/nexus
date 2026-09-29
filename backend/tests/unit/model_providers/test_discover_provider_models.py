from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from nexus.errors import ErrorCode, NexusError
from nexus.model_providers.application import (
    DiscoverProviderModels,
    ProviderDiscoveryPolicy,
    RegisterConfiguredModels,
)
from nexus.model_providers.application._provider_model_discovery import (
    ProviderModelDiscovery,
)
from nexus.model_providers.domain import (
    ConfiguredProvider,
    CredentialReference,
    DefaultModelSelection,
    ModelCandidate,
    ModelType,
    OpenAISettings,
    OrganizationModelProviderConfiguration,
    OrganizationProviderId,
    ProviderCredentialSecret,
    ProviderType,
    ProviderValidationStatus,
)
from nexus.model_providers.ports import (
    CredentialStoreError,
    ProviderModelDiscoveryAuthenticationError,
    ProviderModelDiscoveryRejectedError,
    ProviderModelDiscoveryUnavailableError,
    ProviderModelDiscoveryUnsupportedError,
)
from nexus.ports.rate_limit import RateLimitError


@dataclass
class FakePermissionChecker:
    allowed: bool = True
    permission: str | None = None

    async def has_permission(self, *, permission_key: str, **_kwargs: object) -> bool:
        self.permission = permission_key
        return self.allowed


class FakePersistence:
    def __init__(self, provider: ConfiguredProvider) -> None:
        self.provider = provider

    async def load_configuration(
        self, *, organization_public_id: UUID
    ) -> OrganizationModelProviderConfiguration:
        return OrganizationModelProviderConfiguration(
            organization_public_id=organization_public_id,
            providers=(self.provider,),
            defaults=DefaultModelSelection(),
        )

    async def create_discovered_models(self, **_kwargs: object) -> None:
        return None


class FakeCredentialStore:
    def __init__(self) -> None:
        self.calls = 0
        self.error: Exception | None = None

    async def resolve(self, **_kwargs: object) -> ProviderCredentialSecret:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return ProviderCredentialSecret("credential-value")


class FakeCatalog:
    def __init__(self) -> None:
        self.calls = 0
        self.error: BaseException | None = None

    async def discover(self, **_kwargs: object) -> tuple[ModelCandidate, ...]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return (
            ModelCandidate(
                provider_model_name="gpt-test",
                display_name="GPT Test",
                model_type=ModelType.CHAT,
            ),
        )


class FakeRateLimiter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []
        self.results = [True, True]
        self.error: Exception | None = None

    async def allow(self, *, key: str, limit: int, window_seconds: int) -> bool:
        self.calls.append((key, limit, window_seconds))
        if self.error is not None:
            raise self.error
        return self.results.pop(0)


def _provider() -> ConfiguredProvider:
    return ConfiguredProvider(
        organization_public_id=uuid4(),
        provider_id=OrganizationProviderId(uuid4()),
        provider_type=ProviderType.OPENAI,
        display_name="OpenAI",
        settings=OpenAISettings(),
        enabled=True,
        credential_reference=CredentialReference(uuid4()),
        validation_status=ProviderValidationStatus.VALID,
        last_validated_at=datetime.now(UTC),
    )


def _service(provider: ConfiguredProvider):
    permission = FakePermissionChecker()
    store = FakeCredentialStore()
    catalog = FakeCatalog()
    limiter = FakeRateLimiter()
    service = DiscoverProviderModels(
        permission_checker=permission,  # type: ignore[arg-type]
        discovery=ProviderModelDiscovery(
            persistence=FakePersistence(provider),  # type: ignore[arg-type]
            credential_store=store,  # type: ignore[arg-type]
            catalog=catalog,  # type: ignore[arg-type]
            rate_limiter=limiter,  # type: ignore[arg-type]
            policy=ProviderDiscoveryPolicy(1, 10, 10, 60),
        ),
    )
    return service, permission, store, catalog, limiter


def _execute(service: DiscoverProviderModels, provider: ConfiguredProvider):
    return asyncio.run(
        service.execute(
            organization_public_id=provider.organization_public_id,
            user_public_id=uuid4(),
            provider_public_id=provider.provider_id.value,
        )
    )


def test_discovery_uses_manage_permission_and_resolves_credential() -> None:
    provider = _provider()
    service, permission, store, catalog, limiter = _service(provider)

    result = _execute(service, provider)

    assert result[0].provider_model_name == "gpt-test"
    assert permission.permission == "model_providers.manage"
    assert store.calls == 1
    assert catalog.calls == 1
    assert [call[1:] for call in limiter.calls] == [(10, 60), (1, 10)]


def test_manage_permission_denial_stops_before_rate_limit_credentials_and_discovery() -> (
    None
):
    provider = _provider()
    service, permission, store, catalog, limiter = _service(provider)
    permission.allowed = False

    with pytest.raises(NexusError) as raised:
        _execute(service, provider)

    assert raised.value.code is ErrorCode.FORBIDDEN
    assert permission.permission == "model_providers.manage"
    assert limiter.calls == []
    assert store.calls == 0
    assert catalog.calls == 0


@pytest.mark.parametrize(
    "provider",
    [
        replace(_provider(), enabled=False),
        replace(
            _provider(),
            validation_status=ProviderValidationStatus.UNVALIDATED,
            last_validated_at=None,
        ),
        replace(
            _provider(),
            validation_status=ProviderValidationStatus.INVALID_CREDENTIALS,
        ),
        replace(_provider(), credential_reference=None),
    ],
)
def test_ineligible_provider_stops_before_rate_limit_and_credentials(
    provider: ConfiguredProvider,
) -> None:
    service, _permission, store, catalog, limiter = _service(provider)

    with pytest.raises(NexusError) as raised:
        _execute(service, provider)

    assert raised.value.code is ErrorCode.CONFLICT
    assert limiter.calls == []
    assert store.calls == 0
    assert catalog.calls == 0


def test_rate_limit_stops_before_credential_resolution() -> None:
    provider = _provider()
    service, _permission, store, catalog, limiter = _service(provider)
    limiter.results = [False]

    with pytest.raises(NexusError) as raised:
        _execute(service, provider)

    assert raised.value.code is ErrorCode.RATE_LIMITED
    assert store.calls == 0
    assert catalog.calls == 0


def test_limiter_and_credential_failures_are_safe() -> None:
    provider = _provider()
    service, _permission, store, _catalog, limiter = _service(provider)
    limiter.error = RateLimitError("redis detail")
    with pytest.raises(NexusError) as raised:
        _execute(service, provider)
    assert raised.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert "redis detail" not in raised.value.message

    service, _permission, store, _catalog, _limiter = _service(provider)
    store.error = CredentialStoreError("secret detail")
    with pytest.raises(NexusError) as raised:
        _execute(service, provider)
    assert raised.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert "secret detail" not in raised.value.message


def test_unsupported_discovery_has_distinct_error_code() -> None:
    provider = _provider()
    service, _permission, _store, catalog, _limiter = _service(provider)
    catalog.error = ProviderModelDiscoveryUnsupportedError("provider detail")

    with pytest.raises(NexusError) as raised:
        _execute(service, provider)

    assert raised.value.code is ErrorCode.MODEL_DISCOVERY_UNSUPPORTED
    assert "provider detail" not in raised.value.message


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (
            ProviderModelDiscoveryAuthenticationError("provider secret detail"),
            ErrorCode.CONFLICT,
        ),
        (
            ProviderModelDiscoveryRejectedError("provider rejection detail"),
            ErrorCode.CONFLICT,
        ),
        (
            ProviderModelDiscoveryUnavailableError("provider network detail"),
            ErrorCode.SERVICE_UNAVAILABLE,
        ),
    ],
)
def test_provider_failures_are_normalized_without_detail(
    error: Exception,
    expected_code: ErrorCode,
) -> None:
    provider = _provider()
    service, _permission, _store, catalog, _limiter = _service(provider)
    catalog.error = error

    with pytest.raises(NexusError) as raised:
        _execute(service, provider)

    assert raised.value.code is expected_code
    assert str(error) not in raised.value.message


def test_cancellation_propagates() -> None:
    provider = _provider()
    service, _permission, _store, catalog, _limiter = _service(provider)
    catalog.error = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        _execute(service, provider)


def test_provider_request_rejection_is_non_retryable_conflict() -> None:
    provider = _provider()
    service, _permission, _store, catalog, _limiter = _service(provider)
    catalog.error = ProviderModelDiscoveryRejectedError("provider raw detail")

    with pytest.raises(NexusError) as raised:
        _execute(service, provider)

    assert raised.value.code is ErrorCode.CONFLICT
    assert raised.value.retryable is False
    assert raised.value.message == "The provider rejected the model discovery request."
    assert "provider raw detail" not in raised.value.message


def test_catalog_then_registration_discovery_is_allowed_by_default_policy() -> None:
    provider = _provider()
    permission = FakePermissionChecker()
    store = FakeCredentialStore()
    catalog = FakeCatalog()

    class CountingLimiter:
        def __init__(self) -> None:
            self.provider_calls = 0

        async def allow(self, *, key: str, **_kwargs: object) -> bool:
            if ":provider:" not in key:
                return True
            self.provider_calls += 1
            return self.provider_calls <= 2

    limiter = CountingLimiter()
    persistence = FakePersistence(provider)
    discovery = ProviderModelDiscovery(
        persistence=persistence,  # type: ignore[arg-type]
        credential_store=store,  # type: ignore[arg-type]
        catalog=catalog,  # type: ignore[arg-type]
        rate_limiter=limiter,  # type: ignore[arg-type]
        policy=ProviderDiscoveryPolicy(2, 10, 10, 60),
    )
    catalog_service = DiscoverProviderModels(
        permission_checker=permission,  # type: ignore[arg-type]
        discovery=discovery,
    )
    registration = RegisterConfiguredModels(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=permission,  # type: ignore[arg-type]
        discovery=discovery,
    )

    _execute(catalog_service, provider)
    asyncio.run(
        registration.register_discovered(
            organization_public_id=provider.organization_public_id,
            user_public_id=uuid4(),
            provider_public_id=provider.provider_id.value,
            provider_model_names=("gpt-test",),
        )
    )

    assert catalog.calls == 2
    with pytest.raises(NexusError) as raised:
        _execute(catalog_service, provider)
    assert raised.value.code is ErrorCode.RATE_LIMITED
