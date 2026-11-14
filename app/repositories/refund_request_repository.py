from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.enums import PaymentStatus
from app.models.refund_request import RefundRequest
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
            .options(joinedload(RefundRequest.sale))
            .order_by(RefundRequest.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
