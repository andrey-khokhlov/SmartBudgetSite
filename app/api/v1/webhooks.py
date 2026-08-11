from fastapi import APIRouter, Request, Response, status, HTTPException, Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.dependencies import get_db

from app.services.webhooks.calendly_webhook_service import (
    process_calendly_webhook,
)
from app.services.webhooks.signature_verification_service import (
    CALENDLY_SIGNATURE_HEADER,
    verify_webhook_signature,
)
from app.core.rate_limiting import (
    enforce_calendly_verified_limits,
    enforce_lava_top_verified_limit,
)
from app.services.payment_delivery_orchestration_service import (
    reconcile_payment_and_deliver,
)
from app.services.payment_reconciliation_service import PaymentReconciliationError
from app.services.webhooks.payload_normalizers.lava_top_payment_normalizer import (
    normalize_lava_top_payment_event,
)
from app.services.webhooks.webhook_audit_logger import log_webhook_event
from app.services.webhooks.webhook_audit_statuses import (
    WEBHOOK_STATUS_MALFORMED_PAYLOAD,
    WEBHOOK_STATUS_REJECTED,
    WEBHOOK_STATUS_PROCESSED,
    WEBHOOK_STATUS_RECONCILIATION_MISMATCH,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/calendly")
async def calendly_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """
    Receive Calendly webhook events.

    Business rules:
    - This route must stay thin.
    - Signature verification, JSON parsing, payload normalization, and lifecycle
      processing must be delegated to dedicated boundaries/services.
    - The route must not update consultation entitlements directly.

    Side effects:
    - Emits audit log events for webhook rejection and malformed JSON cases.
    - Delegates successful webhook processing to the webhook orchestration service.

    Invariants / restrictions:
    - Do not parse Calendly-specific payload details in this route.
    - Do not create consultation entitlements from webhook requests.
    - Do not log secrets, raw signatures, or raw payload bodies.
    """

    raw_payload = await request.body()

    is_valid_signature = verify_webhook_signature(
        provider="calendly",
        payload=raw_payload,
        headers=request.headers,
    )

    if not is_valid_signature:
        log_webhook_event(
            provider="calendly",
            event_type="signature_verification",
            status=WEBHOOK_STATUS_REJECTED,
        )

        raise HTTPException(
            status_code=401,
            detail="Invalid webhook signature",
        )

    enforce_calendly_verified_limits(
        request,
        request.headers[CALENDLY_SIGNATURE_HEADER],
    )

    try:
        payload = await request.json()
    except ValueError:
        log_webhook_event(
            provider="calendly",
            event_type="json_parse",
            status=WEBHOOK_STATUS_MALFORMED_PAYLOAD,
        )

        raise HTTPException(
            status_code=400,
            detail="Malformed JSON payload",
        )

    process_calendly_webhook(
        db=db,
        payload=payload,
    )
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/lava-top/payment-result")
async def lava_top_payment_result_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """Authenticate, normalize, and atomically apply one Lava.top result."""

    if not verify_webhook_signature(
        provider="lava_top",
        payload=b"",
        headers=request.headers,
    ):
        log_webhook_event(
            provider="lava_top",
            event_type="authentication",
            status=WEBHOOK_STATUS_REJECTED,
        )
        raise HTTPException(status_code=401, detail="Invalid webhook credentials")

    enforce_lava_top_verified_limit(request)

    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError
        event = normalize_lava_top_payment_event(payload)
    except (ValueError, TypeError):
        log_webhook_event(
            provider="lava_top",
            event_type="payment_result",
            status=WEBHOOK_STATUS_MALFORMED_PAYLOAD,
        )
        raise HTTPException(status_code=400, detail="Malformed webhook payload")

    event_type = f"payment.{event.outcome.value}"
    try:
        outcome = reconcile_payment_and_deliver(db, event)
    except PaymentReconciliationError:
        db.rollback()
        log_webhook_event(
            provider="lava_top",
            event_type=event_type,
            status=WEBHOOK_STATUS_RECONCILIATION_MISMATCH,
            external_payment_id=event.external_payment_id,
        )
        raise HTTPException(
            status_code=409,
            detail="Payment reconciliation requires operator attention",
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Payment reconciliation is temporarily unavailable",
        ) from exc
    except Exception:
        db.rollback()
        raise

    log_webhook_event(
        provider="lava_top",
        event_type=event_type,
        status=WEBHOOK_STATUS_PROCESSED,
        external_payment_id=event.external_payment_id,
        sale_id=outcome.sale_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
