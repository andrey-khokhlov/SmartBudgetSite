import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.enums import PaymentStatus
from app.models.purchase_email_delivery import (
    PurchaseEmailDeliveryStatus,
    PurchaseEmailFailureClassification,
)
from app.repositories.purchase_email_delivery_repository import (
    RecoveryCutoffs,
    email_recovery_is_due,
    get_delivery_by_sale_id_for_update,
    get_delivery_for_update,
    get_delivery_with_fulfillment,
)
from app.services.email_transport import (
    EmailTransport,
    EmailTransportAmbiguousError,
    EmailTransportDefinitiveError,
    EmailTransportIdempotencyConflictError,
    EmailTransportPermanentError,
    EmailTransportTransientError,
    TransactionalEmail,
)
from app.services.purchase_email_renderer import (
    PurchaseEmailExpiredDownloadError,
    PurchaseEmailRenderError,
    render_purchase_email,
)
from app.services.resend_email_transport import ResendEmailTransport
from app.services.webhooks.resend_webhook_service import apply_pending_resend_receipts

logger = logging.getLogger(__name__)

AMBIGUOUS_RETRY_WINDOW = timedelta(hours=23)
RECOVERY_RETRY_INTERVAL = timedelta(minutes=10)
MAX_AUTOMATIC_ATTEMPTS = 3
DEFINITIVE_FAILURE_DIAGNOSTIC = "Purchase email transport definitively failed."
AMBIGUOUS_FAILURE_DIAGNOSTIC = "Purchase email provider outcome is ambiguous."
EXPIRED_DOWNLOAD_DIAGNOSTIC = "Purchase email blocked because download access expired."
RECONCILIATION_DIAGNOSTIC = (
    "Ambiguous purchase email attempt exceeded the safe retry window."
)
IDEMPOTENCY_CONFLICT_DIAGNOSTIC = (
    "Purchase email idempotency conflict requires reconciliation."
)


class PurchaseEmailAttemptResult(StrEnum):
    SENT = "sent"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"
    ALREADY_SENT = "already_sent"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    SKIPPED = "skipped"


def purchase_email_recovery_cutoffs(
    now: datetime, *, allow_sends: bool
) -> RecoveryCutoffs:
    return RecoveryCutoffs(
        pending_before=now
        - timedelta(minutes=settings.PURCHASE_EMAIL_RECOVERY_PENDING_DELAY_MINUTES),
        retry_before=now - RECOVERY_RETRY_INTERVAL,
        ambiguous_before=now - AMBIGUOUS_RETRY_WINDOW,
        max_attempts=MAX_AUTOMATIC_ATTEMPTS,
        allow_sends=allow_sends,
    )


def deliver_purchase_email_after_payment_commit(
    db: Session,
    *,
    sale_id: int,
    transport: EmailTransport | None = None,
    now: datetime | None = None,
    initial_only: bool = False,
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
            initial_only=initial_only,
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
    initial_only: bool = False,
    recovery_allow_sends: bool | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> PurchaseEmailAttemptResult:
    """Claim, commit, send, and persist one purchase-email attempt."""

    delivery = get_delivery_by_sale_id_for_update(db, sale_id=sale_id)
    if delivery is None:
        db.rollback()
        if recovery_allow_sends is not None:
            return PurchaseEmailAttemptResult.SKIPPED
        raise RuntimeError("Purchase email delivery record does not exist.")

    attempted_at = now or clock()
    if recovery_allow_sends is not None:
        cutoffs = purchase_email_recovery_cutoffs(
            attempted_at, allow_sends=recovery_allow_sends
        )
        if not email_recovery_is_due(db, delivery.id, cutoffs):
            db.commit()
            return PurchaseEmailAttemptResult.SKIPPED
    if initial_only and (
        delivery.status != PurchaseEmailDeliveryStatus.PENDING.value
        or delivery.attempt_count != 0
    ):
        db.commit()
        return PurchaseEmailAttemptResult.SKIPPED

    if delivery.status == PurchaseEmailDeliveryStatus.SENT.value:
        db.commit()
        return PurchaseEmailAttemptResult.ALREADY_SENT
    if delivery.status == PurchaseEmailDeliveryStatus.RECONCILIATION_REQUIRED.value:
        db.commit()
        return PurchaseEmailAttemptResult.RECONCILIATION_REQUIRED
    previously_ambiguous = delivery.status == PurchaseEmailDeliveryStatus.SENDING.value
    original_start = delivery.sending_started_at
    if previously_ambiguous:
        if _ambiguous_attempt_is_old(original_start, now=attempted_at):
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
    delivery.failure_classification = None
    delivery_id = delivery.id
    db.commit()

    try:
        message = _build_transactional_email(
            db, delivery_id=delivery_id, now=now or clock()
        )
        db.commit()
        if previously_ambiguous and _ambiguous_attempt_is_old(
            original_start, now=now or clock()
        ):
            current = get_delivery_for_update(db, delivery_id=delivery_id)
            result_at_boundary = PurchaseEmailAttemptResult.SKIPPED
            if (
                current is not None
                and current.status == PurchaseEmailDeliveryStatus.SENDING.value
                and current.sending_started_at == original_start
            ):
                current.status = (
                    PurchaseEmailDeliveryStatus.RECONCILIATION_REQUIRED.value
                )
                current.last_error = RECONCILIATION_DIAGNOSTIC
                result_at_boundary = PurchaseEmailAttemptResult.RECONCILIATION_REQUIRED
            db.commit()
            return result_at_boundary
        result = transport.send(message)
    except EmailTransportIdempotencyConflictError:
        db.rollback()
        current = get_delivery_for_update(db, delivery_id=delivery_id)
        if current is None:
            db.rollback()
            raise RuntimeError("Purchase email delivery record disappeared.")
        if current.status == PurchaseEmailDeliveryStatus.SENT.value:
            db.commit()
            return PurchaseEmailAttemptResult.ALREADY_SENT
        current.status = PurchaseEmailDeliveryStatus.RECONCILIATION_REQUIRED.value
        current.last_error = IDEMPOTENCY_CONFLICT_DIAGNOSTIC
        db.commit()
        return PurchaseEmailAttemptResult.RECONCILIATION_REQUIRED
    except PurchaseEmailExpiredDownloadError:
        db.rollback()
        if previously_ambiguous:
            _record_ambiguous_failure(
                db,
                delivery_id=delivery_id,
                diagnostic=EXPIRED_DOWNLOAD_DIAGNOSTIC,
                classification=PurchaseEmailFailureClassification.PERMANENT,
            )
            return PurchaseEmailAttemptResult.AMBIGUOUS
        _record_definitive_failure(
            db,
            delivery_id=delivery_id,
            diagnostic=EXPIRED_DOWNLOAD_DIAGNOSTIC,
            classification=PurchaseEmailFailureClassification.PERMANENT,
        )
        return PurchaseEmailAttemptResult.FAILED
    except (PurchaseEmailRenderError, EmailTransportDefinitiveError) as exc:
        db.rollback()
        classification = _classify_definitive_failure(exc)
        if previously_ambiguous:
            _record_ambiguous_failure(
                db, delivery_id=delivery_id, classification=classification
            )
            return PurchaseEmailAttemptResult.AMBIGUOUS
        _record_definitive_failure(
            db, delivery_id=delivery_id, classification=classification
        )
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
    current.failure_classification = None
    apply_pending_resend_receipts(db, current, now=datetime.now(UTC))
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
    delivery.failure_classification = PurchaseEmailFailureClassification.UNKNOWN
    delivery.sending_started_at = None
    db.commit()
    logger.info(
        "Purchase email resend explicitly authorized", extra={"sale_id": sale_id}
    )
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
    now: datetime,
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
        now=now if now.tzinfo is not None else now.replace(tzinfo=UTC),
    )
    return TransactionalEmail(
        recipient=delivery.sale.customer_email,
        sender_email=sender_email,
        sender_name=sender_name,
        subject=rendered.subject,
        text_body=rendered.text_body,
        html_body=rendered.html_body,
        idempotency_key=f"purchase-email/{delivery.id}",
        purchase_email_delivery_id=delivery.id,
    )


def _classify_definitive_failure(exc: Exception) -> PurchaseEmailFailureClassification:
    if isinstance(exc, EmailTransportTransientError):
        return PurchaseEmailFailureClassification.TRANSIENT
    if isinstance(exc, (EmailTransportPermanentError, PurchaseEmailRenderError)):
        return PurchaseEmailFailureClassification.PERMANENT
    return PurchaseEmailFailureClassification.UNKNOWN


def _record_definitive_failure(
    db: Session,
    *,
    delivery_id: int,
    diagnostic: str = DEFINITIVE_FAILURE_DIAGNOSTIC,
    classification: PurchaseEmailFailureClassification,
) -> None:
    delivery = get_delivery_for_update(db, delivery_id=delivery_id)
    if delivery is None:
        db.rollback()
        raise RuntimeError("Purchase email delivery record disappeared.")
    if delivery.status not in {
        PurchaseEmailDeliveryStatus.SENT.value,
        PurchaseEmailDeliveryStatus.RECONCILIATION_REQUIRED.value,
    }:
        delivery.status = PurchaseEmailDeliveryStatus.FAILED.value
        delivery.last_error = diagnostic
        delivery.failure_classification = classification
        delivery.sending_started_at = None
    db.commit()


def _record_ambiguous_failure(
    db: Session,
    *,
    delivery_id: int,
    diagnostic: str = AMBIGUOUS_FAILURE_DIAGNOSTIC,
    classification: PurchaseEmailFailureClassification | None = None,
) -> None:
    delivery = get_delivery_for_update(db, delivery_id=delivery_id)
    if delivery is None:
        db.rollback()
        raise RuntimeError("Purchase email delivery record disappeared.")
    if delivery.status not in {
        PurchaseEmailDeliveryStatus.SENT.value,
        PurchaseEmailDeliveryStatus.RECONCILIATION_REQUIRED.value,
    }:
        delivery.status = PurchaseEmailDeliveryStatus.SENDING.value
        delivery.last_error = diagnostic
        delivery.failure_classification = classification
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
