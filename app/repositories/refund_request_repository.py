from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased, joinedload, selectinload

from app.models.enums import PaymentStatus
from app.models.refund_request import RefundRequest
from app.models.refund_request_notification import RefundRequestNotification
from app.models.refund_request_receipt import RefundRequestReceipt
from app.models.sale import Sale
from app.models.sale_item import SaleItem


def find_refund_request_by_token(db: Session, token: str) -> RefundRequest | None:
    return db.scalar(
        select(RefundRequest).where(RefundRequest.submission_token == token)
    )


def find_paid_sale_for_request(db: Session, email: str, reference: str) -> Sale | None:
    return db.scalar(
        select(Sale)
        .where(
            Sale.sale_reference == reference,
            func.lower(func.trim(Sale.customer_email)) == email,
            Sale.payment_status == PaymentStatus.PAID,
        )
        .options(selectinload(Sale.items).joinedload(SaleItem.service_addon))
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def list_refund_requests(
    db: Session, *, offset: int, limit: int
) -> list[RefundRequest]:
    return list(
        db.scalars(
            select(RefundRequest)
            .options(
                joinedload(RefundRequest.sale),
                selectinload(RefundRequest.notifications),
                joinedload(RefundRequest.receipt),
            )
            .order_by(RefundRequest.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )


def read_notification_candidates(
    db: Session, *, now: datetime, limit: int
) -> list[int]:
    entry = RefundRequestNotification
    active = aliased(entry)
    active_send = (
        select(active.id)
        .where(
            active.request_id == entry.request_id,
            active.status == "sending",
            active.next_attempt_at > now,
        )
        .exists()
    )
    return list(
        db.scalars(
            select(entry.request_id)
            .where(
                entry.status.in_(("pending", "sending")),
                entry.next_attempt_at <= now,
                ~active_send,
            )
            .distinct()
            .order_by(entry.request_id)
            .limit(limit)
        )
    )


def lock_request_notifications(
    db: Session, request_id: int
) -> list[RefundRequestNotification]:
    entry = RefundRequestNotification
    return list(
        db.scalars(
            select(entry)
            .where(entry.request_id == request_id)
            .order_by(entry.channel.desc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )


def list_due_receipt_ids(db: Session, *, now: datetime, limit: int) -> list[int]:
    receipt = RefundRequestReceipt
    return list(
        db.scalars(
            select(receipt.request_id)
            .where(
                receipt.status.in_(("pending", "sending")),
                receipt.next_attempt_at <= now,
            )
            .order_by(receipt.next_attempt_at, receipt.request_id)
            .limit(limit)
        )
    )


def lock_receipt(db: Session, request_id: int) -> RefundRequestReceipt | None:
    return db.scalar(
        select(RefundRequestReceipt)
        .where(RefundRequestReceipt.request_id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
