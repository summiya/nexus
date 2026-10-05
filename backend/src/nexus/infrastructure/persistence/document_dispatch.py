"""Short PostgreSQL transactions for outbox leases and request identity reads."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.documents.ports.dispatch import DispatchLease, DocumentDispatchError
from nexus.documents.ports.processing import DocumentProcessingRequested
from nexus.infrastructure.persistence.document import _settle_cancelled_transaction
from nexus.infrastructure.persistence.models import Document, Organization
from nexus.infrastructure.persistence.models import DocumentProcessingRequest as Request


def _identity_query() -> Select[Request, UUID, UUID]:
    return (
        select(Request, Organization.public_id, Document.public_id)
        .join(Organization, Organization.id == Request.organization_id)
        .join(
            Document,
            (Document.id == Request.document_id)
            & (Document.organization_id == Request.organization_id)
            & (Document.source_file_id == Request.source_file_id),
        )
    )


class SqlAlchemyDocumentDispatchPersistence:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def claim(self, *, limit: int, lease_seconds: int) -> list[DispatchLease]:
        if not 1 <= limit <= 20 or not 1 <= lease_seconds <= 600:
            raise ValueError("Invalid document dispatch lease bounds")
        task = asyncio.create_task(self._claim(limit, lease_seconds))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await _settle_cancelled_transaction(task)
            raise

    async def _claim(self, limit: int, lease_seconds: int) -> list[DispatchLease]:
        try:
            async with self._sessions.begin() as session:
                now = cast(
                    datetime,
                    (
                        await session.execute(select(func.clock_timestamp()))
                    ).scalar_one(),
                )
                rows = (
                    await session.execute(
                        _identity_query()
                        .where(
                            Request.dispatched_at.is_(None),
                            Request.dispatch_next_attempt_at <= now,
                            or_(
                                Request.dispatch_lease_until.is_(None),
                                Request.dispatch_lease_until <= now,
                            ),
                        )
                        .order_by(Request.dispatch_next_attempt_at, Request.id)
                        .limit(limit)
                        .with_for_update(of=Request, skip_locked=True)
                    )
                ).all()
                leases = []
                for request, org_id, doc_id in rows:
                    token = uuid4()
                    request.dispatch_lease_token = token
                    request.dispatch_lease_until = now + timedelta(
                        seconds=lease_seconds
                    )
                    request.dispatch_attempts += 1
                    leases.append(
                        DispatchLease(
                            DocumentProcessingRequested(
                                request.public_id, org_id, doc_id
                            ),
                            token,
                            request.dispatch_attempts,
                        )
                    )
                return leases
        except SQLAlchemyError as exc:
            raise DocumentDispatchError("Document dispatch persistence failed") from exc

    async def acknowledge(self, lease: DispatchLease) -> None:
        await self._finish(lease, delay_seconds=None)

    async def retry(self, lease: DispatchLease, *, delay_seconds: int) -> None:
        if not 0 <= delay_seconds <= 60:
            raise ValueError("Invalid document dispatch retry delay")
        await self._finish(lease, delay_seconds=delay_seconds)

    async def _finish(self, lease: DispatchLease, *, delay_seconds: int | None) -> None:
        task = asyncio.create_task(self._finish_transaction(lease, delay_seconds))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await _settle_cancelled_transaction(task)
            raise

    async def _finish_transaction(
        self, lease: DispatchLease, delay_seconds: int | None
    ) -> None:
        try:
            async with self._sessions.begin() as session:
                now = cast(
                    datetime,
                    (
                        await session.execute(select(func.clock_timestamp()))
                    ).scalar_one(),
                )
                values: dict[str, object] = {
                    "dispatch_lease_token": None,
                    "dispatch_lease_until": None,
                }
                if delay_seconds is None:
                    values["dispatched_at"] = func.greatest(now, Request.created_at)
                else:
                    values["dispatch_next_attempt_at"] = now + timedelta(
                        seconds=delay_seconds
                    )
                await session.execute(
                    update(Request)
                    .where(
                        Request.public_id == lease.message.request_public_id,
                        Request.dispatch_lease_token == lease.token,
                        Request.dispatch_lease_until > now,
                        Request.dispatched_at.is_(None),
                    )
                    .values(**values)
                )
        except SQLAlchemyError as exc:
            raise DocumentDispatchError("Document dispatch persistence failed") from exc

    async def matches(self, message: DocumentProcessingRequested) -> bool:
        try:
            async with self._sessions() as session:
                row = await session.scalar(
                    _identity_query().where(
                        Request.public_id == message.request_public_id,
                        Organization.public_id == message.organization_public_id,
                        Document.public_id == message.document_public_id,
                    )
                )
                return row is not None
        except SQLAlchemyError as exc:
            raise DocumentDispatchError("Document request persistence failed") from exc
