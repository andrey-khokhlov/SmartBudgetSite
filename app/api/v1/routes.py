from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, Form
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dependencies import get_db, require_admin
from app.repositories.feedback_repository import FeedbackRepository
from app.schemas.feedback import FeedbackCreateResponse, FeedbackListResponse, FeedbackMessageType
from app.schemas.purchase_check import PurchaseLookupRequest, PurchaseLookupResponse
from app.services.feedback_service import validate_feedback_support_reference
from app.services.purchase_lookup_service import (
    list_verified_product_purchases,
    resolve_verified_product_id,
)

import uuid
import shutil
from app.models.feedback_attachment import FeedbackAttachment

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
    MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
    ALLOWED_TYPES = {
        "image/png",
        "image/jpeg",
        "image/webp",
        "application/pdf",
    }
    ALLOWED_EXTENSIONS = {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".pdf",
    }
    MAX_FILES_COUNT = 5

    upload_path = Path(settings.UPLOAD_DIR)
    upload_path.mkdir(parents=True, exist_ok=True)

    repo = FeedbackRepository(db)

    user_agent = request.headers.get("user-agent")

    files = [
        file
        for file in files
        if not (file.filename == "" and file.size == 0)
    ]

    if len(files) > MAX_FILES_COUNT:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files. Maximum allowed: {MAX_FILES_COUNT}",
        )

    # Validate uploaded files
    for file in files:
        extension = Path(file.filename or "").suffix.lower()

        if not file.filename:
            raise HTTPException(
                status_code=400,
                detail="File must have a filename",
            )

        if extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file extension: {extension or 'unknown'}",
            )

        # Check content type
        if file.content_type not in ALLOWED_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {file.content_type}",
            )

        # Read file to check size
        file.file.seek(0, 2)  # move to end
        size = file.file.tell()

        if size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File too large: {file.filename}",
            )

        file.file.seek(0)

    # 🔐 BACKEND VALIDATION
    product_id = None
    if message_type == "product_feedback":
        if not email:
            raise HTTPException(
                status_code=400,
                detail="Email is required for product feedback",
            )

        product_id = resolve_verified_product_id(
            db=db,
            email=str(email),
            purchase_reference=purchase_reference,
        )

    normalized_support_reference = validate_feedback_support_reference(
        message_type=message_type.value,
        support_reference=support_reference,
    )

    feedback = repo.create(
        message_type=str(message_type.value),
        email=email,
        subject=subject,
        message=message,
        name=name,
        page_url=page_url,
        user_agent=user_agent,
        support_reference=normalized_support_reference,
        product_id=product_id,
    )

    attachments = []
    saved_paths = []

    try:
        for file in files:
            # Generate unique filename
            file_ext = Path(file.filename or "").suffix.lower()
            unique_name = f"{uuid.uuid4().hex}{file_ext}"

            # Build storage path
            file_path = upload_path / unique_name

            # Save file to disk
            with open(file_path, "wb") as f:
                shutil.copyfileobj(file.file, f)

            saved_paths.append(file_path)

            # Create attachment record
            attachment = FeedbackAttachment(
                feedback_id=feedback.id,
                original_filename=file.filename or unique_name,
                storage_type="local",
                storage_key=str(file_path),
                content_type=file.content_type or "application/octet-stream",
                file_size_bytes=file_path.stat().st_size,
            )

            attachments.append(attachment)

        if attachments:
            db.add_all(attachments)
            db.commit()

    except Exception:
        db.rollback()

        for path in saved_paths:
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass

        raise HTTPException(
            status_code=500,
            detail="Failed to save attachments",
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
    payload: PurchaseLookupRequest,
    db: Session = Depends(get_db),
) -> PurchaseLookupResponse:
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

