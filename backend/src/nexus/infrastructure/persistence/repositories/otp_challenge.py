"""SQLAlchemy OTP challenge repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.infrastructure.persistence.models.otp_challenge import OtpChallenge


class SqlAlchemyOtpChallengeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, challenge: OtpChallenge) -> None:
        self._session.add(challenge)
        self._session.flush()

    def get_latest_for_update(
        self,
        *,
        email: str,
        purpose: str,
    ) -> OtpChallenge | None:
        return self._session.scalar(
            select(OtpChallenge)
            .where(
                OtpChallenge.email == email,
                OtpChallenge.purpose == purpose,
            )
            .order_by(OtpChallenge.created_at.desc())
            .limit(1)
            .with_for_update()
        )
