from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest

from nexus.authorization.permissions import PermissionChecker, PermissionCheckError
from nexus.errors import ErrorCode, NexusError
from nexus.files.application import (
    InitiatedFileUpload,
    InitiateFileUpload,
    UploadIntentPolicy,
)
from nexus.files.domain import UPLOAD_CONTEXT_VERSION, UploadContext
from nexus.files.ports import (
    UploadContextProtectionError,
    UploadContextProtector,
    UploadGrant,
    UploadGrantError,
    UploadGrantIssuer,
)

ORGANIZATION_ID = uuid4()
USER_ID = uuid4()
ISSUED_AT = datetime(2026, 9, 25, 12, tzinfo=UTC)
VALIDATED_AT = ISSUED_AT + timedelta(seconds=2)
GRANT_TTL = timedelta(minutes=10)


class FakePermissionChecker:
    def __init__(self, events: list[str], *, allowed: bool = True) -> None:
        self.events = events
        self.allowed = allowed
        self.error: BaseException | None = None
        self.calls: list[tuple[UUID, UUID, str]] = []

    async def has_permission(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        permission_key: str,
    ) -> bool:
        self.events.append("permission")
        self.calls.append((organization_public_id, user_public_id, permission_key))
        if self.error is not None:
            raise self.error
        return self.allowed


class RecordingIntentPolicy:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.policy = UploadIntentPolicy(max_size_bytes=536_870_912)
        self.calls: list[tuple[str, str | None, int]] = []

    def prepare(
        self,
        *,
        original_name: str,
        mime_type: str | None,
        size_bytes: int,
    ) -> object:
        self.events.append("intent")
        self.calls.append((original_name, mime_type, size_bytes))
        return self.policy.prepare(
            original_name=original_name,
            mime_type=mime_type,
            size_bytes=size_bytes,
        )


class FakeUploadGrantIssuer:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.error: BaseException | None = None
        self.effective_expiration: datetime | None = None
        self.calls: list[tuple[str, datetime]] = []

    async def issue_upload_grant(
        self,
        *,
        storage_key: str,
        expires_at: datetime,
    ) -> UploadGrant:
        self.events.append("grant")
        self.calls.append((storage_key, expires_at))
        if self.error is not None:
            raise self.error
        return UploadGrant(
            url="https://storage.example/blob?sig=sensitive",
            method="PUT",
            headers={"x-ms-blob-type": "BlockBlob"},
            expires_at=self.effective_expiration or expires_at,
        )


class FakeUploadContextProtector:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.error: Exception | None = None
        self.contexts: list[UploadContext] = []

    def protect(self, context: UploadContext) -> str:
        self.events.append("protect")
        self.contexts.append(context)
        if self.error is not None:
            raise self.error
        return "nuc1.primary.opaque-protected-context"

    def unprotect(self, value: str) -> UploadContext:
        del value
        raise NotImplementedError


def _clock(*values: datetime) -> Callable[[], datetime]:
    remaining = iter(values)
    return lambda: next(remaining)


def _service(
    *,
    clock: Callable[[], datetime] | None = None,
) -> tuple[
    InitiateFileUpload,
    FakePermissionChecker,
    RecordingIntentPolicy,
    FakeUploadGrantIssuer,
    FakeUploadContextProtector,
    list[str],
]:
    events: list[str] = []
    permission_checker = FakePermissionChecker(events)
    intent_policy = RecordingIntentPolicy(events)
    grant_issuer = FakeUploadGrantIssuer(events)
    protector = FakeUploadContextProtector(events)
    service = InitiateFileUpload(
        intent_policy=cast(UploadIntentPolicy, intent_policy),
        permission_checker=cast(PermissionChecker, permission_checker),
        upload_grant_issuer=cast(UploadGrantIssuer, grant_issuer),
        context_protector=cast(UploadContextProtector, protector),
        grant_ttl=GRANT_TTL,
        clock=clock or _clock(ISSUED_AT, VALIDATED_AT),
    )
    return service, permission_checker, intent_policy, grant_issuer, protector, events


def _execute(service: InitiateFileUpload) -> InitiatedFileUpload:
    return asyncio.run(
        service.execute(
            organization_public_id=ORGANIZATION_ID,
            user_public_id=USER_ID,
            original_name="  report.pdf  ",
            mime_type=" APPLICATION/PDF ",
            declared_size_bytes=42,
        )
    )


def test_execute_authorizes_issues_grant_and_protects_trusted_context() -> None:
    service, checker, policy, issuer, protector, events = _service()

    result = _execute(service)

    assert events == ["permission", "intent", "grant", "protect"]
    assert checker.calls == [(ORGANIZATION_ID, USER_ID, "files.upload")]
    assert policy.calls == [("  report.pdf  ", " APPLICATION/PDF ", 42)]
    assert len(issuer.calls) == 1
    storage_key, requested_expiration = issuer.calls[0]
    assert requested_expiration == ISSUED_AT + GRANT_TTL
    assert result.grant.expires_at == requested_expiration
    assert result.protected_context == "nuc1.primary.opaque-protected-context"

    assert len(protector.contexts) == 1
    context = protector.contexts[0]
    assert context.version == UPLOAD_CONTEXT_VERSION
    assert context.file_public_id.version == 4
    assert context.organization_public_id == ORGANIZATION_ID
    assert context.created_by_user_public_id == USER_ID
    assert context.original_name == "report.pdf"
    assert context.mime_type == "application/pdf"
    assert context.declared_size_bytes == 42
    assert context.storage_key == storage_key
    assert context.issued_at == ISSUED_AT
    assert context.grant_expires_at == requested_expiration
    assert "sensitive" not in repr(result)
    assert result.protected_context not in repr(result)


def test_execute_preserves_zero_declared_size_in_context() -> None:
    service, _, _, _, protector, _ = _service()

    asyncio.run(
        service.execute(
            organization_public_id=ORGANIZATION_ID,
            user_public_id=USER_ID,
            original_name="empty.txt",
            mime_type="text/plain",
            declared_size_bytes=0,
        )
    )

    assert protector.contexts[0].declared_size_bytes == 0


def test_execute_uses_provider_shortened_effective_expiration_in_context() -> None:
    service, _, _, issuer, protector, _ = _service()
    effective_expiration = VALIDATED_AT + timedelta(minutes=3)
    issuer.effective_expiration = effective_expiration

    result = _execute(service)

    assert result.grant.expires_at == effective_expiration
    assert protector.contexts[0].grant_expires_at == effective_expiration


def test_denied_permission_stops_before_validation_grant_and_protection() -> None:
    service, checker, policy, issuer, protector, events = _service()
    checker.allowed = False

    with pytest.raises(NexusError) as captured:
        _execute(service)

    assert captured.value.code is ErrorCode.FORBIDDEN
    assert captured.value.message == "You are not allowed to perform this action."
    assert events == ["permission"]
    assert policy.calls == []
    assert issuer.calls == []
    assert protector.contexts == []


def test_invalid_metadata_stops_before_grant_and_protection() -> None:
    service, _, _, issuer, protector, events = _service()

    with pytest.raises(NexusError) as captured:
        asyncio.run(
            service.execute(
                organization_public_id=ORGANIZATION_ID,
                user_public_id=USER_ID,
                original_name=" ",
                mime_type="application/pdf",
                declared_size_bytes=42,
            )
        )

    assert captured.value.code is ErrorCode.VALIDATION_ERROR
    assert captured.value.message == "File name is invalid."
    assert events == ["permission", "intent"]
    assert issuer.calls == []
    assert protector.contexts == []


def test_permission_infrastructure_failure_is_safe_and_retryable() -> None:
    service, checker, _, issuer, protector, _ = _service()
    failure = PermissionCheckError("database detail")
    checker.error = failure

    with pytest.raises(NexusError) as captured:
        _execute(service)

    error = captured.value
    assert error.code is ErrorCode.SERVICE_UNAVAILABLE
    assert error.message == "Authorization is temporarily unavailable."
    assert error.retryable is True
    assert error.__cause__ is failure
    assert issuer.calls == []
    assert protector.contexts == []


def test_grant_failure_is_safe_and_does_not_protect_context() -> None:
    service, _, _, issuer, protector, _ = _service()
    failure = UploadGrantError("provider credential detail")
    issuer.error = failure

    with pytest.raises(NexusError) as captured:
        _execute(service)

    _assert_upload_unavailable(captured.value, failure)
    assert protector.contexts == []


def test_context_protection_failure_is_safe_after_grant_is_issued() -> None:
    service, _, _, issuer, protector, _ = _service()
    failure = UploadContextProtectionError("crypto detail")
    protector.error = failure

    with pytest.raises(NexusError) as captured:
        _execute(service)

    _assert_upload_unavailable(captured.value, failure)
    assert len(issuer.calls) == 1


@pytest.mark.parametrize(
    "effective_expiration",
    [VALIDATED_AT, ISSUED_AT + GRANT_TTL + timedelta(microseconds=1)],
)
def test_invalid_effective_grant_lifetime_never_protects_context(
    effective_expiration: datetime,
) -> None:
    service, _, _, issuer, protector, _ = _service()
    issuer.effective_expiration = effective_expiration

    with pytest.raises(NexusError) as captured:
        _execute(service)

    _assert_upload_unavailable(captured.value)
    assert protector.contexts == []


@pytest.mark.parametrize("grant_ttl", [timedelta(0), timedelta(seconds=-1)])
def test_service_requires_positive_grant_ttl(grant_ttl: timedelta) -> None:
    _, checker, policy, issuer, protector, _ = _service()

    with pytest.raises(ValueError, match="grant_ttl must be a positive timedelta"):
        InitiateFileUpload(
            intent_policy=cast(UploadIntentPolicy, policy),
            permission_checker=cast(PermissionChecker, checker),
            upload_grant_issuer=cast(UploadGrantIssuer, issuer),
            context_protector=cast(UploadContextProtector, protector),
            grant_ttl=grant_ttl,
        )


def test_service_requires_timezone_aware_clock() -> None:
    service, _, _, issuer, protector, _ = _service(
        clock=lambda: ISSUED_AT.replace(tzinfo=None)
    )

    with pytest.raises(
        ValueError,
        match="Upload initiation clock must be timezone-aware",
    ):
        _execute(service)

    assert issuer.calls == []
    assert protector.contexts == []


@pytest.mark.parametrize("boundary", ["permission", "grant"])
def test_cancellation_at_async_boundary_remains_cancellation(boundary: str) -> None:
    service, checker, _, issuer, _, _ = _service()
    if boundary == "permission":
        checker.error = asyncio.CancelledError()
    else:
        issuer.error = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        _execute(service)


def test_unexpected_programming_failure_is_not_reclassified() -> None:
    service, checker, _, _, _, _ = _service()
    failure = RuntimeError("programming failure")
    checker.error = failure

    with pytest.raises(RuntimeError) as captured:
        _execute(service)

    assert captured.value is failure


def _assert_upload_unavailable(
    error: NexusError,
    cause: Exception | None = None,
) -> None:
    assert error.code is ErrorCode.SERVICE_UNAVAILABLE
    assert error.message == "The file upload could not be initiated."
    assert error.retryable is True
    if cause is not None:
        assert error.__cause__ is cause
