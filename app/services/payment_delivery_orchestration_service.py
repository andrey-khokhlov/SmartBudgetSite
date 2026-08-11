from datetime import datetime

from sqlalchemy.orm import Session

from app.schemas.webhooks import NormalizedPaymentEvent, PaymentOutcome
from app.services.email_transport import EmailTransport
from app.services.payment_reconciliation_service import (
    PaymentReconciliationOutcome,
    reconcile_payment_event,
)
from app.services.purchase_email_delivery_service import (
    deliver_purchase_email_after_payment_commit,
)


def reconcile_payment_and_deliver(
    db: Session,
    event: NormalizedPaymentEvent,
    *,
    expected_sale_id: int | None = None,
    transport: EmailTransport | None = None,
    now: datetime | None = None,
) -> PaymentReconciliationOutcome:
    """Commit authoritative payment fulfillment before attempting email."""

    outcome = reconcile_payment_event(
        db,
        event,
        expected_sale_id=expected_sale_id,
    )
    db.commit()
    if event.outcome == PaymentOutcome.SUCCESS:
        deliver_purchase_email_after_payment_commit(
            db,
            sale_id=outcome.sale_id,
            transport=transport,
            now=now,
        )
    return outcome
