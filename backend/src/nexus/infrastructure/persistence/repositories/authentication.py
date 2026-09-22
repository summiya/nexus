"""SQLAlchemy authentication repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from nexus.authentication.repository import (
    AuthenticationIdentity,
    AuthenticationSession,
    OtpChallenge,
    SignupAccount,
)
from nexus.authorization.bootstrap import provision_administrator_role
from nexus.infrastructure.persistence.models.auth_session import AuthSession
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.infrastructure.persistence.models.otp_challenge import (
    OtpChallenge as OtpChallengeModel,
)
from nexus.infrastructure.persistence.models.user import User
from nexus.infrastructure.persistence.models.user_role import UserRole


class SqlAlchemyAuthenticationRepository:
    """Map authentication records to the existing SQLAlchemy schema."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def user_exists_by_email(self, email: str) -> bool:
        return (
            self._session.scalar(select(User.id).where(User.email == email)) is not None
        )

    def get_identity_by_email(
        self,
        email: str,
    ) -> AuthenticationIdentity | None:
        row = self._session.execute(
            select(User.public_id, Organization.public_id)
            .join(Organization, User.organization_id == Organization.id)
            .where(
                User.email == email,
                User.status == "active",
                User.deleted_at.is_(None),
                Organization.status == "active",
                Organization.deleted_at.is_(None),
            )
        ).one_or_none()
        if row is None:
            return None
        return AuthenticationIdentity(
            user_public_id=row[0],
            organization_public_id=row[1],
        )

    def organization_exists_by_slug(self, slug: str) -> bool:
        return (
            self._session.scalar(
                select(Organization.id).where(Organization.slug == slug)
            )
            is not None
        )

    def add_otp_challenge(self, challenge: OtpChallenge) -> None:
        self._session.add(
            OtpChallengeModel(
                id=challenge.public_id,
                user_id=None,
                email=challenge.email,
                purpose=challenge.purpose,
                code_digest=challenge.code_digest,
                expires_at=challenge.expires_at,
                consumed_at=challenge.consumed_at,
                attempt_count=challenge.attempt_count,
                max_attempts=challenge.max_attempts,
                locked_at=challenge.locked_at,
            )
        )
        self._session.flush()

    def get_latest_otp_challenge_for_update(
        self,
        *,
        email: str,
        purpose: str,
    ) -> OtpChallenge | None:
        model = self._session.scalar(
            select(OtpChallengeModel)
            .where(
                OtpChallengeModel.email == email,
                OtpChallengeModel.purpose == purpose,
            )
            .order_by(OtpChallengeModel.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        return None if model is None else _otp_challenge_record(model)

    def update_otp_challenge(self, challenge: OtpChallenge) -> None:
        model = self._session.get(OtpChallengeModel, challenge.public_id)
        if model is None:
            raise LookupError("OTP challenge does not exist")
        model.attempt_count = challenge.attempt_count
        model.consumed_at = challenge.consumed_at
        model.locked_at = challenge.locked_at
        self._session.flush()

    def create_organization_administrator(
        self,
        account: SignupAccount,
    ) -> AuthenticationIdentity:
        organization = Organization(
            public_id=account.organization_public_id,
            name=account.organization_name,
            slug=account.organization_slug,
            status="active",
        )
        self._session.add(organization)
        self._session.flush()

        user = User(
            public_id=account.user_public_id,
            organization_id=organization.id,
            email=account.email,
            display_name=account.display_name,
            status="active",
            email_verified_at=account.email_verified_at,
        )
        self._session.add(user)
        self._session.flush()

        administrator_role = provision_administrator_role(
            self._session,
            organization.id,
        )
        self._session.add(
            UserRole(
                organization_id=organization.id,
                user_id=user.id,
                role_id=administrator_role.id,
            )
        )
        self._session.flush()
        return AuthenticationIdentity(
            user_public_id=user.public_id,
            organization_public_id=organization.public_id,
        )

    def add_session(self, session: AuthenticationSession) -> None:
        user_id = self._user_id(session.identity)
        self._session.add(
            AuthSession(
                public_id=session.public_id,
                user_id=user_id,
                refresh_token_hash=session.refresh_token_hash,
                expires_at=session.expires_at,
                revoked_at=session.revoked_at,
                last_used_at=session.last_used_at,
            )
        )
        self._session.flush()

    def get_session_by_refresh_token_hash_for_update(
        self,
        refresh_token_hash: str,
    ) -> AuthenticationSession | None:
        model = self._session.scalar(
            select(AuthSession)
            .options(joinedload(AuthSession.user).joinedload(User.organization))
            .where(AuthSession.refresh_token_hash == refresh_token_hash)
            .with_for_update(of=AuthSession)
        )
        return None if model is None else _authentication_session_record(model)

    def update_session(self, session: AuthenticationSession) -> None:
        model = self._session.scalar(
            select(AuthSession)
            .where(AuthSession.public_id == session.public_id)
            .with_for_update()
        )
        if model is None:
            raise LookupError("Authentication session does not exist")
        model.refresh_token_hash = session.refresh_token_hash
        model.revoked_at = session.revoked_at
        model.last_used_at = session.last_used_at
        self._session.flush()

    def _user_id(self, identity: AuthenticationIdentity) -> int:
        user_id = self._session.scalar(
            select(User.id)
            .join(Organization, User.organization_id == Organization.id)
            .where(
                User.public_id == identity.user_public_id,
                Organization.public_id == identity.organization_public_id,
            )
        )
        if user_id is None:
            raise LookupError("Authentication identity does not exist")
        return user_id


def _otp_challenge_record(model: OtpChallengeModel) -> OtpChallenge:
    return OtpChallenge(
        public_id=model.id,
        email=model.email,
        purpose=model.purpose,
        code_digest=model.code_digest,
        expires_at=model.expires_at,
        max_attempts=model.max_attempts,
        attempt_count=model.attempt_count,
        consumed_at=model.consumed_at,
        locked_at=model.locked_at,
    )


def _authentication_session_record(model: AuthSession) -> AuthenticationSession:
    return AuthenticationSession(
        public_id=model.public_id,
        identity=AuthenticationIdentity(
            user_public_id=model.user.public_id,
            organization_public_id=model.user.organization.public_id,
        ),
        refresh_token_hash=model.refresh_token_hash,
        expires_at=model.expires_at,
        revoked_at=model.revoked_at,
        last_used_at=model.last_used_at,
    )
