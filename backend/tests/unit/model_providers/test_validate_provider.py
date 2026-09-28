from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from nexus.errors import ErrorCode, NexusError
from nexus.model_providers.application import (
    ProviderValidationPolicy,
    ValidateModelProvider,
)
from nexus.model_providers.domain import (
    ConfiguredProvider,
    CredentialReference,
    DefaultModelSelection,
    OpenAISettings,
    OrganizationModelProviderConfiguration,
    OrganizationProviderId,
    ProviderCredentialSecret,
    ProviderSettings,
    ProviderType,
    ProviderValidationStatus,
)
from nexus.model_providers.ports import (
    CredentialStoreError,
    ModelProviderConflictError,
)
from nexus.ports.rate_limit import RateLimitError


@dataclass
class FakePermissionChecker:
    allowed: bool = True

    async def has_permission(self, **_kwargs: object) -> bool:
        return self.allowed


class FakePersistence:
    def __init__(self, provider: ConfiguredProvider) -> None:
        self.provider = provider
        self.recorded: list[
            tuple[
                ProviderSettings, CredentialReference | None, ProviderValidationStatus
            ]
        ] = []
        self.record_error: Exception | None = None

    async def load_configuration(
        self, *, organization_public_id: UUID
    ) -> OrganizationModelProviderConfiguration:
        return OrganizationModelProviderConfiguration(
            organization_public_id=organization_public_id,
            providers=(self.provider,),
            defaults=DefaultModelSelection(),
        )

    async def record_provider_validation(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        expected_settings: ProviderSettings,
        expected_credential_reference: CredentialReference | None,
        status: ProviderValidationStatus,
    ) -> ConfiguredProvider:
        if self.record_error is not None:
            raise self.record_error
        self.recorded.append((expected_settings, expected_credential_reference, status))
        self.provider = replace(
            self.provider,
            validation_status=status,
            last_validated_at=datetime(2026, 9, 29, tzinfo=UTC),
        )
        return self.provider


class FakeCredentialStore:
    def __init__(self) -> None:
        self.calls = 0
        self.error: Exception | None = None

    async def resolve(self, **_kwargs: object) -> ProviderCredentialSecret:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return ProviderCredentialSecret("secret-value")


@dataclass
class FakeValidator:
    result: ProviderValidationStatus = ProviderValidationStatus.VALID
    calls: int = 0

    async def validate(self, **_kwargs: object) -> ProviderValidationStatus:
        self.calls += 1
        return self.result


class FakeRateLimiter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []
        self.results: list[bool] = [True, True]
        self.error: Exception | None = None

    async def allow(self, *, key: str, limit: int, window_seconds: int) -> bool:
        self.calls.append((key, limit, window_seconds))
        if self.error is not None:
            raise self.error
        return self.results.pop(0)


def _provider(*, credential: bool = True) -> ConfiguredProvider:
    return ConfiguredProvider(
        organization_public_id=uuid4(),
        provider_id=OrganizationProviderId(uuid4()),
        provider_type=ProviderType.OPENAI,
        display_name="OpenAI",
        settings=OpenAISettings(),
        enabled=False,
        credential_reference=CredentialReference(uuid4()) if credential else None,
    )


def _service(
    provider: ConfiguredProvider,
) -> tuple[
    ValidateModelProvider,
    FakePersistence,
    FakeCredentialStore,
    FakeValidator,
    FakeRateLimiter,
]:
    persistence = FakePersistence(provider)
    store = FakeCredentialStore()
    validator = FakeValidator()
    limiter = FakeRateLimiter()
    service = ValidateModelProvider(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=FakePermissionChecker(),  # type: ignore[arg-type]
        credential_store=store,  # type: ignore[arg-type]
        validator=validator,  # type: ignore[arg-type]
        rate_limiter=limiter,  # type: ignore[arg-type]
        policy=ProviderValidationPolicy(
            provider_max_requests=1,
            provider_window_seconds=5,
            organization_max_requests=20,
            organization_window_seconds=60,
        ),
    )
    return service, persistence, store, validator, limiter


def test_validation_resolves_credential_and_records_result() -> None:
    provider = _provider()
    service, persistence, store, validator, limiter = _service(provider)

    result = asyncio.run(
        service.execute(
            organization_public_id=provider.organization_public_id,
            user_public_id=uuid4(),
            provider_public_id=provider.provider_id.value,
        )
    )

    assert result.validation_status is ProviderValidationStatus.VALID
    assert store.calls == 1
    assert validator.calls == 1
    assert persistence.recorded == [
        (
            provider.settings,
            provider.credential_reference,
            ProviderValidationStatus.VALID,
        )
    ]
    assert limiter.calls == [
        (
            f"model-provider-validation:organization:{provider.organization_public_id}",
            20,
            60,
        ),
        (
            (
                "model-provider-validation:provider:"
                f"{provider.organization_public_id}:{provider.provider_id.value}"
            ),
            1,
            5,
        ),
    ]


def test_missing_credential_records_unsupported_without_store_access() -> None:
    provider = _provider(credential=False)
    service, persistence, store, validator, _limiter = _service(provider)

    result = asyncio.run(
        service.execute(
            organization_public_id=provider.organization_public_id,
            user_public_id=uuid4(),
            provider_public_id=provider.provider_id.value,
        )
    )

    assert (
        result.validation_status is ProviderValidationStatus.UNSUPPORTED_CONFIGURATION
    )
    assert store.calls == 0
    assert validator.calls == 0
    assert (
        persistence.recorded[0][2] is ProviderValidationStatus.UNSUPPORTED_CONFIGURATION
    )


@pytest.mark.parametrize("results", [[False], [True, False]])
def test_either_rate_limit_stops_before_secret_resolution(
    results: list[bool],
) -> None:
    provider = _provider()
    service, _persistence, store, validator, limiter = _service(provider)
    limiter.results = results

    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.execute(
                organization_public_id=provider.organization_public_id,
                user_public_id=uuid4(),
                provider_public_id=provider.provider_id.value,
            )
        )

    assert raised.value.code is ErrorCode.RATE_LIMITED
    assert store.calls == 0
    assert validator.calls == 0


def test_rate_limiter_failure_is_service_unavailable() -> None:
    provider = _provider()
    service, _persistence, _store, _validator, limiter = _service(provider)
    limiter.error = RateLimitError("must not leak")

    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.execute(
                organization_public_id=provider.organization_public_id,
                user_public_id=uuid4(),
                provider_public_id=provider.provider_id.value,
            )
        )

    assert raised.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert "must not leak" not in raised.value.message


def test_credential_store_failure_is_service_unavailable() -> None:
    provider = _provider()
    service, _persistence, store, _validator, _limiter = _service(provider)
    store.error = CredentialStoreError("must not leak")

    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.execute(
                organization_public_id=provider.organization_public_id,
                user_public_id=uuid4(),
                provider_public_id=provider.provider_id.value,
            )
        )

    assert raised.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert "must not leak" not in raised.value.message


def test_stale_validation_result_is_conflict() -> None:
    provider = _provider()
    service, persistence, _store, _validator, _limiter = _service(provider)
    persistence.record_error = ModelProviderConflictError("must not leak")

    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.execute(
                organization_public_id=provider.organization_public_id,
                user_public_id=uuid4(),
                provider_public_id=provider.provider_id.value,
            )
        )

    assert raised.value.code is ErrorCode.CONFLICT
    assert "must not leak" not in raised.value.message


def test_cancellation_from_validator_propagates() -> None:
    provider = _provider()
    service, _persistence, _store, _validator, _limiter = _service(provider)

    class CancelledValidator:
        async def validate(self, **_kwargs: object) -> ProviderValidationStatus:
            raise asyncio.CancelledError

    object.__setattr__(service, "validator", CancelledValidator())

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            service.execute(
                organization_public_id=provider.organization_public_id,
                user_public_id=uuid4(),
                provider_public_id=provider.provider_id.value,
            )
        )


def test_manage_permission_is_required_before_rate_limit_or_credential_access() -> None:
    provider = _provider()
    service, _persistence, store, validator, limiter = _service(provider)
    object.__setattr__(service, "permission_checker", FakePermissionChecker(False))

    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.execute(
                organization_public_id=provider.organization_public_id,
                user_public_id=uuid4(),
                provider_public_id=provider.provider_id.value,
            )
        )

    assert raised.value.code is ErrorCode.FORBIDDEN
    assert limiter.calls == []
    assert store.calls == 0
    assert validator.calls == 0
