from decimal import Decimal, InvalidOperation

from app.schemas.webhooks import NormalizedPaymentEvent, PaymentOutcome
from app.services.lava_top.client import (
    LavaTopInvoiceDetails,
    LavaTopInvoiceStatus,
)

SUPPORTED_EVENT_OUTCOMES = {
    "payment.success": PaymentOutcome.SUCCESS,
    "payment.failed": PaymentOutcome.FAILED,
}


def normalize_lava_top_payment_event(payload: dict) -> NormalizedPaymentEvent:
    """Normalize one supported Lava.top payment-result webhook payload."""

    event_type = payload.get("eventType")
    external_payment_id = payload.get("contractId")
    if event_type not in SUPPORTED_EVENT_OUTCOMES:
        raise ValueError("Unsupported Lava.top payment event type.")
    if not isinstance(external_payment_id, str) or not external_payment_id.strip():
        raise ValueError("Lava.top payment event has no invoice identity.")

    amount = _optional_decimal(payload.get("amount"))
    currency = payload.get("currency")
    if currency is not None:
        if not isinstance(currency, str) or len(currency.strip()) != 3:
            raise ValueError("Invalid Lava.top payment currency.")
        currency = currency.strip().upper()

    return NormalizedPaymentEvent(
        provider="lava_top",
        external_payment_id=external_payment_id.strip(),
        outcome=SUPPORTED_EVENT_OUTCOMES[event_type],
        amount=amount,
        currency=currency,
    )


def normalize_lava_top_invoice(
    invoice: LavaTopInvoiceDetails,
) -> NormalizedPaymentEvent | None:
    """Normalize a terminal invoice lookup; unresolved states return None."""

    outcomes = {
        LavaTopInvoiceStatus.COMPLETED: PaymentOutcome.SUCCESS,
        LavaTopInvoiceStatus.FAILED: PaymentOutcome.FAILED,
    }
    outcome = outcomes.get(invoice.status)
    if outcome is None:
        return None
    return NormalizedPaymentEvent(
        provider="lava_top",
        external_payment_id=invoice.invoice_id,
        outcome=outcome,
        amount=invoice.amount,
        currency=invoice.currency,
    )


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Invalid Lava.top payment amount.")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid Lava.top payment amount.") from exc
