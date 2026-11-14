import logging
import re
from smtplib import SMTPException
from datetime import UTC, datetime

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.i18n import t
from app.core.sale_reference import SALE_REFERENCE_PATTERN
from app.models.enums import SaleItemType
from app.models.refund_request import RefundRequest
from app.repositories.refund_request_repository import (
    find_paid_sale_for_request,
    find_refund_request_by_token,
)
from app.services import mail_service
from app.services.refund_eligibility_service import (
    VoluntaryRefundWindowStatus,
    assess_voluntary_refund_window,
)

logger = logging.getLogger(__name__)
EMAIL_ADAPTER = TypeAdapter(EmailStr)
MAX_MESSAGE_LENGTH = 2000
SUBMISSION_TOKEN_PATTERN = re.compile(r"[0-9a-f]{64}")


class RefundRequestValidationError(ValueError):
    pass


class RefundRequestPersistenceError(Exception):
    pass


def _verify_replay(existing: RefundRequest, email: str, reference: str) -> str:
    if (existing.customer_email, existing.purchase_reference) != (email, reference):
        raise RefundRequestValidationError("refund_request_invalid_purchase")
    return existing.language


def submit_refund_request(
    db: Session,
    *,
    email: str,
    reference: str,
    message: str,
    language: str,
    submission_token: str,
) -> str:
    if not SUBMISSION_TOKEN_PATTERN.fullmatch(submission_token):
        raise RefundRequestValidationError("refund_request_invalid_submission")
    try:
        email = str(EMAIL_ADAPTER.validate_python(email.strip().lower()))
    except ValidationError:
        raise RefundRequestValidationError("refund_request_invalid_purchase") from None
    reference = reference.strip()
    if len(email) > 200 or not SALE_REFERENCE_PATTERN.fullmatch(reference):
        raise RefundRequestValidationError("refund_request_invalid_purchase")
    message = message.strip()
    if len(message) > MAX_MESSAGE_LENGTH or "\x00" in message:
        raise RefundRequestValidationError("refund_request_invalid_message")
    if language not in {"ru", "en"}:
        raise RefundRequestValidationError("refund_request_invalid_language")

    try:
        with db.begin():
            existing = find_refund_request_by_token(db, submission_token)
            if existing is not None:
                return _verify_replay(existing, email, reference)
            sale = find_paid_sale_for_request(db, email, reference)
            if sale is None:
                existing = find_refund_request_by_token(db, submission_token)
                if existing is not None:
                    return _verify_replay(existing, email, reference)
                raise RefundRequestValidationError("refund_request_invalid_purchase")

            submitted_at = datetime.now(UTC)
            item_types = [item.item_type for item in sale.items]
            deadline = None
            window_status = None
            if item_types == [SaleItemType.PRODUCT]:
                composition = "product"
                assessment = assess_voluntary_refund_window(
                    sale.paid_at, now=submitted_at
                )
                window_status = assessment.status
                deadline = assessment.deadline
            elif (
                item_types == [SaleItemType.SERVICE]
                and sale.items[0].service_addon is not None
                and sale.items[0].service_addon.service_type == "consultation"
                and sale.items[0].service_addon.usage_type == "standalone"
            ):
                composition = "consultation"
            else:
                composition = "mixed" if len(set(item_types)) > 1 else "legacy"
                window_status = VoluntaryRefundWindowStatus.MANUAL_REVIEW
            db.add(
                RefundRequest(
                    submission_token=submission_token,
                    sale_id=sale.id,
                    purchase_reference=reference,
                    customer_email=email,
                    submitted_at=submitted_at,
                    language=language,
                    message=message or None,
                    composition=composition,
                    window_status=window_status,
                    window_deadline=deadline,
                    status="pending",
                )
            )
    except IntegrityError:
        # The failed transaction has rolled back. Only a committed token match
        # turns the integrity error into a replay.
        try:
            with db.begin():
                existing = find_refund_request_by_token(db, submission_token)
                if existing is not None:
                    return _verify_replay(existing, email, reference)
        except SQLAlchemyError:
            pass
        logger.error("Could not persist refund request")
        raise RefundRequestPersistenceError from None
    except SQLAlchemyError:
        logger.error("Could not persist refund request")
        raise RefundRequestPersistenceError from None

    try:
        mail_service.send_email(
            to_email=email,
            subject=t(language, "refund_request_receipt_subject"),
            body=t(language, "refund_request_success"),
        )
    except (SMTPException, OSError, ValueError):
        logger.warning("Refund request receipt could not be sent")
    return language
