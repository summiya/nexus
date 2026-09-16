"""Passwordless signup verification/completion use case."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from nexus.application.authentication.email import WelcomeEmailSender
from nexus.domain.organizations import normalize_slug
from nexus.errors import ErrorCode, NexusError
from nexus.infrastructure.mailer import EmailDeliveryError
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.infrastructure.persistence.models.user import User
from nexus.infrastructure.persistence.models.user_role import UserRole
from nexus.logging import get_logger
from nexus.ports.authorization import AdministratorRoleProvisioner
from nexus.ports.repositories.organization import OrganizationRepository
from nexus.ports.repositories.user import UserRepository
from nexus.ports.repositories.user_role import UserRoleRepository
from nexus.ports.transaction import TransactionManager
from nexus.services.authentication_session import (
    AuthenticationSessionService,
    SessionTokenResult,
)
from nexus.services.authentication_validation import normalize_display_text
from nexus.services.otp import (
    OtpPurpose,
    OtpVerificationFailed,
    OtpVerificationService,
    otp_verification_error,
)

logger = get_logger(__name__)

_SIGNUP_PURPOSE: OtpPurpose = "signup"


@dataclass(frozen=True)
class SignupVerificationRequest:
    email: str
    otp: str
    organization_name: str
    first_name: str
    last_name: str


@dataclass(frozen=True)
class SignupVerificationResult:
    status: str
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class SignupVerificationService:
    """Complete passwordless signup after verifying a signup OTP."""

    def __init__(
        self,
        *,
        transaction: TransactionManager,
        user_repository: UserRepository,
        organization_repository: OrganizationRepository,
        user_role_repository: UserRoleRepository,
        administrator_role_provisioner: AdministratorRoleProvisioner,
        otp_verifier: OtpVerificationService,
        session_service: AuthenticationSessionService,
        welcome_email_sender: WelcomeEmailSender,
    ) -> None:
        self._transaction = transaction
        self._user_repository = user_repository
        self._organization_repository = organization_repository
        self._user_role_repository = user_role_repository
        self._administrator_role_provisioner = administrator_role_provisioner
        self._otp_verifier = otp_verifier
        self._session_service = session_service
        self._welcome_email_sender = welcome_email_sender

    def complete_signup(
        self,
        *,
        request: SignupVerificationRequest,
    ) -> SignupVerificationResult:
        organization_name = normalize_display_text(
            request.organization_name,
            "organization_name",
            max_length=255,
        )
        first_name = normalize_display_text(
            request.first_name,
            "first_name",
            max_length=100,
        )
        last_name = normalize_display_text(
            request.last_name,
            "last_name",
            max_length=100,
        )
        organization_slug = self._normalize_organization_slug(organization_name)
        display_name = f"{first_name} {last_name}"

        try:
            verified = self._otp_verifier.verify(
                email=request.email,
                otp=request.otp,
                purpose=_SIGNUP_PURPOSE,
            )
            self._reject_existing_user(verified.email)
            self._reject_existing_organization(organization_slug)

            organization = Organization(
                name=organization_name,
                slug=organization_slug,
                status="active",
            )
            self._organization_repository.add(organization)

            user = User(
                organization=organization,
                email=verified.email,
                display_name=display_name,
                status="active",
                email_verified_at=datetime.now(UTC),
            )
            self._user_repository.add(user)

            administrator_role = (
                self._administrator_role_provisioner.provision_for_organization(
                    organization.id,
                )
            )
            self._user_role_repository.add(
                UserRole(
                    organization_id=organization.id,
                    user_id=user.id,
                    role_id=administrator_role.id,
                )
            )
            verified.challenge.consumed_at = datetime.now(UTC)
            token_result = self._session_service.create_session(
                user=user,
            )
            self._transaction.commit()
        except OtpVerificationFailed as exc:
            if exc.persist_attempt_state:
                self._transaction.commit()
            else:
                self._transaction.rollback()
            raise otp_verification_error() from exc
        except NexusError:
            self._transaction.rollback()
            raise
        except Exception:
            self._transaction.rollback()
            raise

        self._send_welcome_email(email=verified.email, display_name=display_name)
        return _result_from_tokens(token_result)

    def _normalize_organization_slug(self, organization_name: str) -> str:
        try:
            slug = normalize_slug(organization_name)
        except ValueError as exc:
            raise NexusError(
                ErrorCode.VALIDATION_ERROR,
                "The request validation failed.",
                details={"field": "organization_name"},
            ) from exc
        if len(slug) > 128:
            raise NexusError(
                ErrorCode.VALIDATION_ERROR,
                "The request validation failed.",
                details={"field": "organization_name"},
            )
        return slug

    def _reject_existing_user(self, email: str) -> None:
        if self._user_repository.exists_by_email(email):
            raise NexusError(
                ErrorCode.CONFLICT,
                "The request conflicts with the current resource state.",
            )

    def _reject_existing_organization(self, slug: str) -> None:
        if self._organization_repository.exists_by_slug(slug):
            raise NexusError(
                ErrorCode.CONFLICT,
                "The request conflicts with the current resource state.",
            )

    def _send_welcome_email(self, *, email: str, display_name: str) -> None:
        try:
            self._welcome_email_sender.send_welcome_email(
                email=email,
                display_name=display_name,
            )
        except EmailDeliveryError:
            logger.warning("signup_welcome_email_delivery_failed")


def _result_from_tokens(token_result: SessionTokenResult) -> SignupVerificationResult:
    return SignupVerificationResult(
        status="completed",
        access_token=token_result.access_token,
        refresh_token=token_result.refresh_token,
        token_type=token_result.token_type,
        expires_in=token_result.expires_in,
    )
