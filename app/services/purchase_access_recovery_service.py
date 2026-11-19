import hmac
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.download_entitlement import (
    DownloadEntitlement,
    DownloadEntitlementStatus,
)
from app.models.enums import PaymentStatus, SaleItemType
from app.models.purchase_access_recovery import PurchaseAccessRecovery
from app.models.purchase_access_recovery import RecoveryDeliveryStatus as Delivery
from app.models.purchase_email_delivery import PurchaseEmailDeliveryStatus
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.repositories.download_entitlement_repository import (
    DownloadEntitlementRepository,
)
from app.repositories.purchase_access_recovery_repository import (
    latest_recovery,
    lock_recovery,
    recovery_for_request,
)
from app.repositories.purchase_email_delivery_repository import (
    get_delivery_by_sale_id_for_update,
)
from app.repositories.refund_operation_repository import RefundOperationRepository
from app.services.download_entitlement_service import (
    reissue_download_entitlement,
    validate_download_entitlement,
)
from app.services.email_transport import (
    EmailTransport,
    EmailTransportAmbiguousError,
    EmailTransportDefinitiveError,
    EmailTransportIdempotencyConflictError,
    TransactionalEmail,
)
from app.services.payment_service import (
    CheckoutValidationError,
    normalize_checkout_email,
)
from app.services.purchase_email_delivery_service import AMBIGUOUS_RETRY_WINDOW
from app.services.purchase_email_renderer import (
    PurchaseEmailRenderError,
    render_purchase_email,
)
from app.services.resend_email_transport import ResendEmailTransport

VERIFICATION_METHODS = {
    "provider_dashboard": "Payment provider dashboard",
    "verified_provider_record": "Independently verified provider payment record",
}
MAX_REASON_LENGTH = 500
SEND_LEASE = timedelta(minutes=2)
VERIFY_CONFIRMATION = "independent_payment_verified"
UNRESOLVED_SEND = {
    Delivery.SENDING,
    Delivery.AMBIGUOUS,
    Delivery.RECONCILIATION_REQUIRED,
}


class RecoveryInputError(ValueError):
    pass


class RecoveryConflictError(Exception):
    pass


@dataclass(frozen=True)
class RecoveryEmailClaim:
    message: TransactionalEmail
    attempt: int
    safe_until: datetime
    previously_ambiguous: bool


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _eligible_product_item(sale: Sale, *, has_refund: bool) -> SaleItem:
    if len(sale.items) != 1 or sale.items[0].item_type != SaleItemType.PRODUCT:
        raise RecoveryConflictError(
            "Recovery requires a product-only Sale. Review consultation Sales manually."
        )
    if sale.payment_status != PaymentStatus.PAID or has_refund:
        raise RecoveryConflictError(
            "Recovery requires a paid Sale without a refund operation."
        )
    if (
        not (sale.payment_provider or "").strip()
        or not (sale.external_payment_id or "").strip()
    ):
        raise RecoveryConflictError(
            "The Sale has no verifiable payment-provider identity."
        )
    return sale.items[0]


def _validate_original_release(
    item: SaleItem, entitlement: DownloadEntitlement | None
) -> DownloadEntitlement:
    if (
        entitlement is None
        or item.product_release_id is None
        or entitlement.release_id != item.product_release_id
        or entitlement.release is None
    ):
        raise RecoveryConflictError(
            "The original purchased release could not be verified."
        )
    if (
        entitlement.status
        not in {DownloadEntitlementStatus.AVAILABLE, DownloadEntitlementStatus.EXPIRED}
        or entitlement.completed_at is not None
    ):
        raise RecoveryConflictError("The download entitlement requires manual review.")
    return entitlement


def _check_preparation(
    current: PurchaseAccessRecovery | None, original_status: str | None
) -> None:
    if original_status == PurchaseEmailDeliveryStatus.SENDING:
        raise RecoveryConflictError(
            "Resolve the original purchase email attempt before recovery."
        )
    if current is not None and current.delivery_status in UNRESOLVED_SEND:
        raise RecoveryConflictError(
            "Resolve the existing recovery delivery before preparing another."
        )


def recovery_admin_state(
    db: Session, sale: Sale
) -> tuple[PurchaseAccessRecovery | None, str | None, str | None]:
    current = latest_recovery(db, sale.id)
    try:
        item = _eligible_product_item(
            sale, has_refund=sale.refund_operation is not None
        )
        _validate_original_release(item, item.download_entitlement)
    except RecoveryConflictError as exc:
        return current, str(exc), None
    try:
        original = sale.purchase_email_delivery
        _check_preparation(current, original.status if original else None)
    except RecoveryConflictError as exc:
        return current, None, str(exc)
    return current, None, None


def _lock_sale(db: Session, sale_id: int) -> Sale:
    sale = RefundOperationRepository(db).lock_sale(sale_id)
    if sale is None:
        raise RecoveryConflictError("The Sale could not be found.")
    return sale


def _lock_eligible_grant(db: Session, sale: Sale) -> DownloadEntitlement:
    refund = RefundOperationRepository(db).get_by_sale_id(sale.id)
    item = _eligible_product_item(sale, has_refund=refund is not None)
    grant = DownloadEntitlementRepository(db).get_by_sale_item_id(
        item.id, for_update=True
    )
    return _validate_original_release(item, grant)


def prepare_purchase_access_recovery(
    db: Session,
    *,
    sale_id: int,
    request_id: str,
    expected_recovery_id: int,
    verification: str,
    verification_method: str,
    reason: str,
    corrected_email: str = "",
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> str:
    if (
        verification != VERIFY_CONFIRMATION
        or verification_method not in VERIFICATION_METHODS
    ):
        raise RecoveryInputError(
            "Explicit verification using payment-provider evidence is required."
        )
    reason = reason.strip()
    if not reason or len(reason) > MAX_REASON_LENGTH or "\x00" in reason:
        raise RecoveryInputError("Enter a recovery reason of 1 to 500 characters.")
    if re.fullmatch("[0-9a-f]{32}", request_id) is None:
        raise RecoveryInputError("The recovery form identity is invalid.")
    try:
        email = (
            normalize_checkout_email(corrected_email)
            if corrected_email.strip()
            else None
        )
    except CheckoutValidationError as exc:
        raise RecoveryInputError(str(exc)) from exc

    with db.begin():
        sale = _lock_sale(db, sale_id)
        if recovery_for_request(db, sale_id, request_id) is not None:
            return "already_prepared"
        current = latest_recovery(db, sale_id, for_update=True)
        if expected_recovery_id != (current.id if current else 0):
            raise RecoveryConflictError(
                "This recovery form is stale. Reload the Sale detail."
            )
        original = get_delivery_by_sale_id_for_update(db, sale_id=sale_id)
        _check_preparation(current, original.status if original else None)
        grant = _lock_eligible_grant(db, sale)

        now = clock()
        recipient = email or sale.customer_email
        db.add(
            PurchaseAccessRecovery(
                sale_id=sale.id,
                entitlement_id=grant.id,
                request_id=request_id,
                reason=reason,
                verification_method=verification_method,
                verified_at=now,
                previous_email=(
                    sale.customer_email if recipient != sale.customer_email else None
                ),
                recipient=recipient,
                previous_status=grant.status,
                previous_expires_at=grant.expires_at,
                previous_attempt_count=grant.attempt_count,
                previous_first_attempt_at=grant.first_attempt_at,
                previous_last_attempt_at=grant.last_attempt_at,
            )
        )
        sale.customer_email = recipient
        reissue_download_entitlement(db, grant, now=now)
    return "prepared"


def _build_email(
    sale: Sale, recovery: PurchaseAccessRecovery, now: datetime
) -> TransactionalEmail:
    base_url = (settings.PUBLIC_BASE_URL or "").strip()
    sender_email, sender_name = (
        settings.MAIL_FROM_EMAIL.strip(),
        settings.MAIL_FROM_NAME.strip(),
    )
    if not (base_url and sender_email and sender_name):
        raise PurchaseEmailRenderError(
            "Purchase email delivery configuration is incomplete."
        )
    rendered = render_purchase_email(sale, public_base_url=base_url, now=now)
    return TransactionalEmail(
        recipient=recovery.recipient,
        sender_email=sender_email,
        sender_name=sender_name,
        subject=rendered.subject,
        text_body=rendered.text_body,
        html_body=rendered.html_body,
        idempotency_key=f"purchase-access-recovery/{recovery.id}",
        purchase_access_recovery_id=recovery.id,
    )


def _require_reconciliation(recovery: PurchaseAccessRecovery, error: str) -> str:
    recovery.delivery_status = Delivery.RECONCILIATION_REQUIRED
    recovery.last_error = error
    return Delivery.RECONCILIATION_REQUIRED


def _claim_send(
    db: Session,
    *,
    sale_id: int,
    recovery_id: int,
    expected_attempt_count: int,
    clock: Callable[[], datetime],
) -> RecoveryEmailClaim | str:
    with db.begin():
        sale = _lock_sale(db, sale_id)
        recovery = latest_recovery(db, sale_id, for_update=True)
        if recovery is None or recovery.id != recovery_id:
            raise RecoveryConflictError(
                "This recovery is no longer current. Reload the Sale detail."
            )
        if recovery.delivery_status in {
            Delivery.ACCEPTED,
            Delivery.RECONCILIATION_REQUIRED,
        }:
            return recovery.delivery_status
        if recovery.attempt_count != expected_attempt_count:
            return recovery.delivery_status

        grant = _lock_eligible_grant(db, sale)
        if (
            grant.id != recovery.entitlement_id
            or sale.customer_email != recovery.recipient
        ):
            return _require_reconciliation(recovery, "recovery_identity_changed")

        now = clock()
        previously_ambiguous = recovery.delivery_status in {
            Delivery.SENDING,
            Delivery.AMBIGUOUS,
        }
        if recovery.delivery_status == Delivery.SENDING and (
            recovery.last_attempt_at is not None
            and now < _utc(recovery.last_attempt_at) + SEND_LEASE
        ):
            return Delivery.SENDING
        first_attempt = (
            _utc(recovery.first_attempt_at) if recovery.first_attempt_at else now
        )
        safe_until = min(first_attempt + AMBIGUOUS_RETRY_WINDOW, _utc(grant.expires_at))
        if (
            recovery.first_attempt_at is not None
            and now >= first_attempt + AMBIGUOUS_RETRY_WINDOW
        ):
            return _require_reconciliation(recovery, "retry_window_elapsed")

        try:
            validate_download_entitlement(grant, now=now)
        except HTTPException:
            if previously_ambiguous:
                return _require_reconciliation(recovery, "download_unavailable")
            return "download_unavailable"
        try:
            message = _build_email(sale, recovery, now)
        except PurchaseEmailRenderError:
            if previously_ambiguous:
                return _require_reconciliation(recovery, "render_unavailable")
            recovery.delivery_status = Delivery.FAILED
            recovery.last_error = "render_unavailable"
            return Delivery.FAILED

        payload = json.dumps(asdict(message), sort_keys=True, separators=(",", ":"))
        # A credential change can also change the provider's idempotency namespace.
        fingerprint = hmac.new(
            (settings.RESEND_API_KEY or "").strip().encode("utf-8"),
            payload.encode("utf-8"),
            sha256,
        ).hexdigest()
        if (
            recovery.payload_fingerprint is not None
            and recovery.payload_fingerprint != fingerprint
        ):
            return _require_reconciliation(recovery, "payload_changed")

        recovery.delivery_status = Delivery.SENDING
        recovery.payload_fingerprint = fingerprint
        recovery.first_attempt_at = first_attempt
        recovery.last_attempt_at = now
        recovery.attempt_count += 1
        return RecoveryEmailClaim(
            message, recovery.attempt_count, safe_until, previously_ambiguous
        )


def _finish_send(
    db: Session,
    recovery_id: int,
    attempt: int,
    *,
    status: Delivery,
    now: datetime,
    error: str | None = None,
    provider_message_id: str | None = None,
) -> str:
    with db.begin():
        recovery = lock_recovery(db, recovery_id)
        if (
            recovery is None
            or recovery.attempt_count != attempt
            or recovery.delivery_status != Delivery.SENDING
        ):
            return "stale_attempt"
        recovery.delivery_status = status
        if status == Delivery.ACCEPTED:
            recovery.last_error = None
        elif error is not None:
            recovery.last_error = error
        if provider_message_id is not None:
            recovery.provider_message_id = provider_message_id
            recovery.accepted_at = now
        return status


def send_purchase_access_recovery(
    db: Session,
    *,
    sale_id: int,
    recovery_id: int,
    expected_attempt_count: int,
    transport: EmailTransport | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> str:
    if transport is None and not settings.PURCHASE_EMAIL_DELIVERY_ENABLED:
        return "disabled"
    claim = _claim_send(
        db,
        sale_id=sale_id,
        recovery_id=recovery_id,
        expected_attempt_count=expected_attempt_count,
        clock=clock,
    )
    if isinstance(claim, str):
        return claim

    status, error, provider_message_id = Delivery.ACCEPTED, None, None
    if clock() >= claim.safe_until:
        status, error = Delivery.RECONCILIATION_REQUIRED, "send_window_elapsed"
    else:
        try:
            result = (transport or ResendEmailTransport()).send(claim.message)
        except EmailTransportIdempotencyConflictError:
            status, error = Delivery.RECONCILIATION_REQUIRED, "idempotency_conflict"
        except EmailTransportAmbiguousError:
            status, error = Delivery.AMBIGUOUS, "ambiguous_transport"
        except EmailTransportDefinitiveError:
            status = (
                Delivery.AMBIGUOUS if claim.previously_ambiguous else Delivery.FAILED
            )
            error = "definitive_transport_failure"
        else:
            provider_message_id = result.provider_message_id
    return _finish_send(
        db,
        recovery_id,
        claim.attempt,
        status=status,
        error=error,
        provider_message_id=provider_message_id,
        now=clock(),
    )
