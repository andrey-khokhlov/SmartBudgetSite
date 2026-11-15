import logging
import smtplib
import ssl
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.i18n import t
from app.models.refund_request import RefundRequest
from app.repositories.lava_top_payment_recovery_repository import lock_recovery_pass
from app.repositories.refund_request_repository import (
    list_due_receipt_ids,
    lock_receipt,
)
from app.services import mail_service

logger = logging.getLogger(__name__)
RETRY_MINUTES = (1, 2, 5, 15, 30, 60)
MAX_ATTEMPTS = 7
MAX_RECEIPTS = 20
LEASE = timedelta(minutes=2)
RECOVERY_LOCK_ID = 812194340106


@dataclass(frozen=True)
class ReceiptClaim:
    attempt: int
    email: str
    language: str


def _claim(db: Session, request_id: int, now: datetime) -> ReceiptClaim | None:
    with db.begin():
        receipt = lock_receipt(db, request_id)
        if receipt is None or receipt.status not in {"pending", "sending"}:
            return None
        due = receipt.next_attempt_at
        if due is None or due.replace(tzinfo=due.tzinfo or UTC) > now:
            return None
        if receipt.status == "sending":
            receipt.failure_classification = "ambiguous"
            if receipt.attempt_count >= MAX_ATTEMPTS:
                receipt.status = "failed"
                receipt.sending_started_at = receipt.next_attempt_at = None
            else:
                receipt.status = "pending"
                receipt.next_attempt_at = now + timedelta(
                    minutes=RETRY_MINUTES[receipt.attempt_count - 1]
                )
                receipt.sending_started_at = None
            return None
        request = db.get(RefundRequest, request_id)
        receipt.status = "sending"
        receipt.attempt_count += 1
        receipt.last_attempt_at = receipt.sending_started_at = now
        receipt.next_attempt_at = now + LEASE
        return ReceiptClaim(
            receipt.attempt_count, request.customer_email, request.language
        )


def _smtp_outcome(claim: ReceiptClaim) -> str | None:
    try:
        mail_service.send_email(
            to_email=claim.email,
            subject=t(claim.language, "refund_request_receipt_subject"),
            body=t(claim.language, "refund_request_success"),
            timeout=5,
        )
    except (
        smtplib.SMTPAuthenticationError,
        smtplib.SMTPNotSupportedError,
        ssl.SSLCertVerificationError,
        ValueError,
    ):
        return "configuration"
    except smtplib.SMTPRecipientsRefused as exc:
        return (
            "temporary"
            if any(400 <= code < 500 for code, _ in exc.recipients.values())
            else "permanent"
        )
    except smtplib.SMTPResponseException as exc:
        return "temporary" if 400 <= exc.smtp_code < 500 else "permanent"
    except (smtplib.SMTPException, OSError):
        return "ambiguous"
    return None


def deliver_refund_request_receipt(
    db: Session,
    request_id: int,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> str:
    claim = _claim(db, request_id, clock())
    if claim is None:
        return "not_claimed"
    outcome = _smtp_outcome(claim)
    with db.begin():
        receipt = lock_receipt(db, request_id)
        if (
            receipt is None
            or receipt.status != "sending"
            or receipt.attempt_count != claim.attempt
        ):
            return "stale_claim"
        now = clock()
        receipt.sending_started_at = receipt.next_attempt_at = None
        receipt.failure_classification = outcome
        if outcome is None:
            receipt.status = "accepted"
            receipt.accepted_at = now
        elif outcome in {"configuration", "permanent"} or claim.attempt >= MAX_ATTEMPTS:
            receipt.status = "failed"
        else:
            receipt.status = "pending"
            receipt.next_attempt_at = now + timedelta(
                minutes=RETRY_MINUTES[claim.attempt - 1]
            )
        if outcome is not None:
            logger.warning("Refund request receipt could not be sent")
        return receipt.status


def recover_refund_request_receipts(
    db: Session,
    *,
    dry_run: bool = False,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict:
    if dry_run:
        with db.begin():
            selected = list_due_receipt_ids(db, now=clock(), limit=MAX_RECEIPTS)
        return {"status": "dry_run", "selected": len(selected), "by_result": {}}
    with lock_recovery_pass(db.get_bind(), lock_id=RECOVERY_LOCK_ID) as acquired:
        if not acquired:
            return {"status": "already_running", "selected": 0, "by_result": {}}
        with db.begin():
            selected = list_due_receipt_ids(db, now=clock(), limit=MAX_RECEIPTS)
        results = Counter(
            deliver_refund_request_receipt(db, request_id, clock=clock)
            for request_id in selected
        )
        return {
            "status": "completed",
            "selected": len(selected),
            "by_result": dict(results),
        }
