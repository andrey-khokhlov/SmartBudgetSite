from typing import List

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_admin
from app.repositories.feedback_repository import FeedbackRepository
from app.schemas.feedback import (
    FeedbackCreateResponse,
    FeedbackListResponse,
    FeedbackMessageType,
)
from app.schemas.purchase_check import PurchaseLookupRequest, PurchaseLookupResponse
from app.services.feedback_service import FeedbackAttachmentInput, submit_feedback
from app.services.purchase_lookup_service import (
    list_verified_product_purchases,
)
from app.core.rate_limiting import enforce_purchase_email_limit

from app.api.v1.webhooks import router as webhook_router

router = APIRouter(prefix="/v1", tags=["v1"])

router.include_router(webhook_router)


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/version")
def version() -> dict:
    return {"version": "v1"}


@router.post("/feedback", response_model=FeedbackCreateResponse)
def create_feedback(
    request: Request,
    message_type: FeedbackMessageType = Form(...),
    subject: str = Form(...),
    message: str = Form(..., min_length=10, max_length=2000),
    email: str = Form(""),
    name: str | None = Form(None),
    page_url: str | None = Form(None),
    support_reference: str | None = Form(None),
    purchase_reference: str | None = Form(None),
    files: List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    files = [file for file in files if not (file.filename == "" and file.size == 0)]
    feedback = submit_feedback(
        db=db,
        message_type=message_type.value,
        email=email,
        subject=subject,
        message=message,
        name=name,
        page_url=page_url,
        user_agent=request.headers.get("user-agent"),
        support_reference=support_reference,
        purchase_reference=purchase_reference,
        attachments=[
            FeedbackAttachmentInput(
                filename=file.filename,
                content_type=file.content_type,
                file=file.file,
            )
            for file in files
        ],
    )

    return {
        "status": "ok",
        "id": feedback.id,
    }


@router.get(
    "/feedback/recent",
    response_model=FeedbackListResponse,
    dependencies=[Depends(require_admin)],
)
def get_recent_feedback(
    limit: int = 20,
    db: Session = Depends(get_db),
):
    repo = FeedbackRepository(db)
    items = repo.get_recent(limit=limit)

    return {
        "items": items,
        "count": len(items),
    }


@router.patch(
    "/feedback/{feedback_id}/resolve",
    dependencies=[Depends(require_admin)],
)
def resolve_feedback(
    feedback_id: int,
    db: Session = Depends(get_db),
):
    repo = FeedbackRepository(db)
    feedback = repo.mark_resolved(feedback_id)

    if feedback is None:
        return {"status": "not_found"}

    return {
        "status": "ok",
        "id": feedback.id,
        "is_resolved": feedback.is_resolved,
    }


@router.post(
    "/check-purchase",
    response_model=PurchaseLookupResponse,
    response_model_exclude_none=True,
)
def check_purchase(
    request: Request,
    payload: PurchaseLookupRequest,
    db: Session = Depends(get_db),
) -> PurchaseLookupResponse:
    enforce_purchase_email_limit(request, str(payload.email))
    purchases = list_verified_product_purchases(
        db=db,
        email=str(payload.email),
    )
    if not purchases:
        return PurchaseLookupResponse(verified=False)

    return PurchaseLookupResponse(
        verified=True,
        purchases=purchases,
    )
