from fastapi import APIRouter, Request, Response, status, HTTPException, Depends
from sqlalchemy.orm import Session
from app.dependencies import get_db

from app.services.webhooks.calendly_webhook_service import (
    process_calendly_webhook,
)
from app.services.webhooks.signature_verification_service import (
    verify_webhook_signature,
)
from app.services.webhooks.webhook_audit_logger import log_webhook_event
from app.services.webhooks.webhook_audit_statuses import (
    WEBHOOK_STATUS_MALFORMED_PAYLOAD,
    WEBHOOK_STATUS_REJECTED,
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
