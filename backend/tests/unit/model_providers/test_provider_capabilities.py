from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from nexus.authorization import PermissionCheckError
from nexus.errors import ErrorCode, NexusError
from nexus.model_providers.application import GetModelProviderCapabilities


class PermissionCheckerStub:
    def __init__(self, results: dict[str, bool]) -> None:
        self.results = results
        self.calls: list[tuple[UUID, UUID, str]] = []
        self.error: Exception | None = None

    async def has_permission(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        permission_key: str,
    ) -> bool:
        self.calls.append((organization_public_id, user_public_id, permission_key))
        if self.error is not None:
            raise self.error
        return self.results[permission_key]


@pytest.mark.parametrize(
    ("can_read", "can_manage"),
    [(False, False), (True, False), (True, True)],
)
def test_capabilities_report_effective_permissions_without_requiring_read(
    can_read: bool,
    can_manage: bool,
) -> None:
    organization_id = uuid4()
    user_id = uuid4()
    checker = PermissionCheckerStub(
        {
            "model_providers.read": can_read,
            "model_providers.manage": can_manage,
        }
    )

    result = asyncio.run(
        GetModelProviderCapabilities(checker).execute(
            organization_public_id=organization_id,
            user_public_id=user_id,
        )
    )

    assert result.can_read is can_read
    assert result.can_manage is can_manage
    assert checker.calls == [
        (organization_id, user_id, "model_providers.read"),
        (organization_id, user_id, "model_providers.manage"),
    ]


def test_capabilities_normalize_permission_infrastructure_failure() -> None:
    checker = PermissionCheckerStub(
        {"model_providers.read": False, "model_providers.manage": False}
    )
    checker.error = PermissionCheckError("database detail")

    with pytest.raises(NexusError) as raised:
        asyncio.run(
            GetModelProviderCapabilities(checker).execute(
                organization_public_id=uuid4(),
                user_public_id=uuid4(),
            )
        )

    assert raised.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert raised.value.retryable is True
    assert "database detail" not in str(raised.value)
