import logging
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.enums import PaymentStatus
from app.models.purchase_email_delivery import PurchaseEmailDeliveryStatus
from app.repositories.purchase_email_delivery_repository import (
    get_delivery_by_sale_id_for_update,
    get_delivery_for_update,
    get_delivery_with_fulfillment,
)
from app.services.email_transport import (
    EmailTransport,
    EmailTransportAmbiguousError,
    EmailTransportDefinitiveError,
    TransactionalEmail,
)
from app.services.purchase_email_renderer import (
    PurchaseEmailRenderError,
    render_purchase_email,
)
from app.services.resend_email_transport import ResendEmailTransport

logger = logging.getLogger(__name__)

AMBIGUOUS_RETRY_WINDOW = timedelta(hours=23)
DEFINITIVE_FAILURE_DIAGNOSTIC = "Purchase email transport definitively failed."
AMBIGUOUS_FAILURE_DIAGNOSTIC = "Purchase email provider outcome is ambiguous."
RECONCILIATION_DIAGNOSTIC = (
    "Ambiguous purchase email attempt exceeded the safe retry window."
)


class PurchaseEmailAttemptResult(StrEnum):
    SENT = "sent"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"
    ALREADY_SENT = "already_sent"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"


def deliver_purchase_email_after_payment_commit(
    db: Session,
    *,
    sale_id: int,
    transport: EmailTransport | None = None,
    now: datetime | None = None,
) -> PurchaseEmailAttemptResult:
    """Attempt delivery without allowing email failure to alter payment truth."""

    if transport is None and not settings.PURCHASE_EMAIL_DELIVERY_ENABLED:
        return PurchaseEmailAttemptResult.DISABLED

    try:
        return attempt_purchase_email_delivery(
            db,
            sale_id=sale_id,
            transport=transport or ResendEmailTransport(),
            now=now,
        )
    except Exception:
        # Payment is already committed. Keep an unexpected delivery outcome
        # isolated and leave a claimed attempt in its durable ambiguous state.
        db.rollback()
        logger.error(
            "Purchase email delivery attempt is temporarily unavailable",
            extra={"sale_id": sale_id},
        )
        return PurchaseEmailAttemptResult.UNAVAILABLE


def attempt_purchase_email_delivery(
    db: Session,
    *,
    sale_id: int,
    transport: EmailTransport,
    now: datetime | None = None,
) -> PurchaseEmailAttemptResult:
    """Claim, commit, send, and persist one purchase-email attempt."""

    attempted_at = now or datetime.now(UTC)
    delivery = get_delivery_by_sale_id_for_update(db, sale_id=sale_id)
    if delivery is None:
        db.rollback()
        raise RuntimeError("Purchase email delivery record does not exist.")

    if delivery.status == PurchaseEmailDeliveryStatus.SENT.value:
        db.commit()
        return PurchaseEmailAttemptResult.ALREADY_SENT
    if delivery.status == PurchaseEmailDeliveryStatus.RECONCILIATION_REQUIRED.value:
        db.commit()
        return PurchaseEmailAttemptResult.RECONCILIATION_REQUIRED
    if delivery.status == PurchaseEmailDeliveryStatus.SENDING.value:
        if _ambiguous_attempt_is_old(delivery.sending_started_at, now=attempted_at):
            delivery.status = PurchaseEmailDeliveryStatus.RECONCILIATION_REQUIRED.value
            delivery.last_error = RECONCILIATION_DIAGNOSTIC
            db.commit()
            return PurchaseEmailAttemptResult.RECONCILIATION_REQUIRED
    elif delivery.status not in {
        PurchaseEmailDeliveryStatus.PENDING.value,
        PurchaseEmailDeliveryStatus.FAILED.value,
    }:
        db.rollback()
        raise RuntimeError("Purchase email delivery status is unsupported.")
    else:
        delivery.sending_started_at = attempted_at

    delivery.status = PurchaseEmailDeliveryStatus.SENDING.value
    delivery.attempt_count += 1
    delivery.last_attempt_at = attempted_at
    delivery.last_error = None
    delivery_id = delivery.id
    db.commit()

    try:
        message = _build_transactional_email(db, delivery_id=delivery_id)
        db.commit()
        result = transport.send(message)
    except (PurchaseEmailRenderError, EmailTransportDefinitiveError):
        db.rollback()
        _record_definitive_failure(db, delivery_id=delivery_id)
        return PurchaseEmailAttemptResult.FAILED
    except EmailTransportAmbiguousError:
        db.rollback()
        _record_ambiguous_failure(db, delivery_id=delivery_id)
        return PurchaseEmailAttemptResult.AMBIGUOUS

    current = get_delivery_for_update(db, delivery_id=delivery_id)
    if current is None:
        db.rollback()
        raise RuntimeError("Purchase email delivery record disappeared.")
    if current.status == PurchaseEmailDeliveryStatus.SENT.value:
        db.commit()
        return PurchaseEmailAttemptResult.ALREADY_SENT

    current.status = PurchaseEmailDeliveryStatus.SENT.value
    current.sent_at = attempted_at
    current.provider_message_id = result.provider_message_id
    current.last_error = None
    db.commit()
    return PurchaseEmailAttemptResult.SENT


def authorize_reconciliation_resend(
    db: Session,
    *,
    sale_id: int,
    provider_confirmed_not_sent: bool,
    transport: EmailTransport | None = None,
    now: datetime | None = None,
) -> PurchaseEmailAttemptResult:
    """Explicitly authorize resend only after provider reconciliation."""

    if not provider_confirmed_not_sent:
        raise ValueError("Provider reconciliation confirmation is required.")
    if transport is None and not settings.PURCHASE_EMAIL_DELIVERY_ENABLED:
        return PurchaseEmailAttemptResult.DISABLED

    delivery = get_delivery_by_sale_id_for_update(db, sale_id=sale_id)
    if delivery is None:
        db.rollback()
        raise RuntimeError("Purchase email delivery record does not exist.")
    if delivery.status != PurchaseEmailDeliveryStatus.RECONCILIATION_REQUIRED.value:
        db.commit()
        if delivery.status == PurchaseEmailDeliveryStatus.SENT.value:
            return PurchaseEmailAttemptResult.ALREADY_SENT
        return PurchaseEmailAttemptResult.UNAVAILABLE

    delivery.status = PurchaseEmailDeliveryStatus.FAILED.value
    delivery.last_error = None
    delivery.sending_started_at = None
    db.commit()
    return deliver_purchase_email_after_payment_commit(
        db,
        sale_id=sale_id,
        transport=transport,
        now=now,
    )


def _build_transactional_email(
    db: Session,
    *,
    delivery_id: int,
) -> TransactionalEmail:
    delivery = get_delivery_with_fulfillment(db, delivery_id=delivery_id)
    if delivery is None or delivery.sale.payment_status != PaymentStatus.PAID:
        raise PurchaseEmailRenderError("Purchase is not eligible for email delivery.")

    public_base_url = (settings.PUBLIC_BASE_URL or "").strip()
    sender_email = settings.MAIL_FROM_EMAIL.strip()
    sender_name = settings.MAIL_FROM_NAME.strip()
    if not public_base_url or not sender_email or not sender_name:
        raise PurchaseEmailRenderError(
            "Purchase email delivery configuration is incomplete."
        )

    rendered = render_purchase_email(
        delivery.sale,
        public_base_url=public_base_url,
        support_email=sender_email,
    )
    return TransactionalEmail(
        recipient=delivery.sale.customer_email,
        sender_email=sender_email,
        sender_name=sender_name,
        subject=rendered.subject,
        text_body=rendered.text_body,
        html_body=rendered.html_body,
        idempotency_key=f"purchase-email/{delivery.id}",
    )


def _record_definitive_failure(db: Session, *, delivery_id: int) -> None:
    delivery = get_delivery_for_update(db, delivery_id=delivery_id)
    if delivery is None:
        db.rollback()
        raise RuntimeError("Purchase email delivery record disappeared.")
    if delivery.status != PurchaseEmailDeliveryStatus.SENT.value:
        delivery.status = PurchaseEmailDeliveryStatus.FAILED.value
        delivery.last_error = DEFINITIVE_FAILURE_DIAGNOSTIC
        delivery.sending_started_at = None
    db.commit()


def _record_ambiguous_failure(db: Session, *, delivery_id: int) -> None:
    delivery = get_delivery_for_update(db, delivery_id=delivery_id)
    if delivery is None:
        db.rollback()
        raise RuntimeError("Purchase email delivery record disappeared.")
    if delivery.status not in {
        PurchaseEmailDeliveryStatus.SENT.value,
        PurchaseEmailDeliveryStatus.RECONCILIATION_REQUIRED.value,
    }:
        delivery.status = PurchaseEmailDeliveryStatus.SENDING.value
        delivery.last_error = AMBIGUOUS_FAILURE_DIAGNOSTIC
    db.commit()


def _ambiguous_attempt_is_old(
    last_attempt_at: datetime | None,
    *,
    now: datetime,
) -> bool:
    if last_attempt_at is None:
        return True
    normalized_last_attempt = last_attempt_at
    if normalized_last_attempt.tzinfo is None:
        normalized_last_attempt = normalized_last_attempt.replace(tzinfo=UTC)
    normalized_now = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return normalized_now - normalized_last_attempt >= AMBIGUOUS_RETRY_WINDOW
