from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

import httpx

from app.core.config import settings


class LavaTopProviderError(Exception):
    """Base error for controlled Lava.top provider failures."""


class LavaTopConfigurationError(LavaTopProviderError):
    """Raised when required Lava.top server configuration is absent."""


class LavaTopRequestError(LavaTopProviderError):
    """Raised when Lava.top cannot successfully process the invoice request."""


class LavaTopResponseError(LavaTopProviderError):
    """Raised when Lava.top returns an unusable success response."""


@dataclass(frozen=True)
class LavaTopInvoice:
    invoice_id: str
    payment_url: str


class LavaTopInvoiceStatus(StrEnum):
    NEW = "NEW"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class LavaTopInvoiceDetails:
    invoice_id: str
    status: LavaTopInvoiceStatus
    amount: Decimal | None = None
    currency: str | None = None


def create_invoice(
    *,
    email: str,
    offer_id: str,
    currency: str,
    amount: Decimal,
) -> LavaTopInvoice:
    """Create a hosted Lava.top invoice using server-owned credentials."""

    api_key = (settings.LAVA_TOP_API_KEY or "").strip()
    if not api_key:
        raise LavaTopConfigurationError("Lava.top API key is not configured.")

    try:
        response = httpx.post(
            f"{settings.LAVA_TOP_API_BASE_URL.rstrip('/')}/api/v3/invoice",
            headers={"X-Api-Key": api_key},
            json={
                "email": email,
                "offerId": offer_id,
                "currency": currency,
                "amount": float(amount),
            },
            timeout=httpx.Timeout(10.0, connect=5.0),
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise LavaTopRequestError("Lava.top invoice creation failed.") from exc

    try:
        payload = response.json()
        invoice_id = payload["id"]
        payment_url = payload["paymentUrl"]
    except (ValueError, KeyError, TypeError) as exc:
        raise LavaTopResponseError(
            "Lava.top returned an invalid invoice response."
        ) from exc

    if not isinstance(invoice_id, str) or not invoice_id.strip():
        raise LavaTopResponseError("Lava.top returned an invalid invoice id.")
    if not isinstance(payment_url, str) or not payment_url.strip():
        raise LavaTopResponseError("Lava.top returned an invalid payment URL.")

    return LavaTopInvoice(invoice_id=invoice_id, payment_url=payment_url)


def get_invoice(invoice_id: str) -> LavaTopInvoiceDetails:
    """Retrieve one Lava.top invoice by its exact provider identity."""

    normalized_invoice_id = invoice_id.strip()
    if not normalized_invoice_id:
        raise ValueError("Lava.top invoice id must not be empty.")

    api_key = (settings.LAVA_TOP_API_KEY or "").strip()
    if not api_key:
        raise LavaTopConfigurationError("Lava.top API key is not configured.")

    url = (
        f"{settings.LAVA_TOP_API_BASE_URL.rstrip('/')}"
        f"/api/v2/invoices/{normalized_invoice_id}"
    )
    try:
        response = httpx.get(
            url,
            headers={"X-Api-Key": api_key},
            timeout=httpx.Timeout(10.0, connect=5.0),
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise LavaTopRequestError("Lava.top invoice lookup failed.") from exc

    try:
        payload = response.json()
        returned_id = payload["id"]
        invoice_status = LavaTopInvoiceStatus(str(payload["status"]).upper())
        receipt = payload.get("receipt")
        amount = (
            Decimal(str(receipt["amount"]))
            if isinstance(receipt, dict) and receipt.get("amount") is not None
            else None
        )
        currency = (
            str(receipt["currency"]).upper()
            if isinstance(receipt, dict) and receipt.get("currency") is not None
            else None
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise LavaTopResponseError(
            "Lava.top returned an invalid invoice lookup response."
        ) from exc

    if returned_id != normalized_invoice_id:
        raise LavaTopResponseError("Lava.top returned a different invoice identity.")
    if currency is not None and len(currency) != 3:
        raise LavaTopResponseError("Lava.top returned an invalid currency.")

    return LavaTopInvoiceDetails(
        invoice_id=returned_id,
        status=invoice_status,
        amount=amount,
        currency=currency,
    )
