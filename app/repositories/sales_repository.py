from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.enums import PaymentStatus
from app.models.sale import Sale
from app.models.sale_item import SaleItem


def has_paid_product_purchase_for_email(
    db: Session,
    email: str,
) -> bool:
    stmt = (
        select(Sale.id)
        .join(SaleItem, SaleItem.sale_id == Sale.id)
        .where(
            Sale.customer_email == email,
            Sale.payment_status == PaymentStatus.PAID,
            SaleItem.item_type == "product",
        )
        .limit(1)
    )

    return db.execute(stmt).first() is not None


def list_admin_sales(
    db: Session,
    status: str | None = None,
    customer_email: str | None = None,
    item_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Sale]:
    """
    Return recent sales with purchased items for admin backoffice.

    Business rules:
    - Admin sales view starts as read-only operational visibility.
    - Sale is an order header.
    - SaleItem rows are the source of truth for purchased products/services.
    - Newest sales are shown first.
    - MVP list is intentionally limited to avoid loading unbounded history.

    Side effects:
    - None. Read-only query.

    Invariants / restrictions:
    - Does not mutate payment or fulfillment state.
    - Legacy sales.product_id must not be used for ownership display.
    """

    stmt = (
        select(Sale)
        .options(selectinload(Sale.items))
    )

    if status:
        stmt = stmt.where(Sale.payment_status == status)

    if customer_email:
        normalized_customer_email = customer_email.strip().lower()

        if normalized_customer_email:
            stmt = stmt.where(Sale.customer_email.ilike(f"%{normalized_customer_email}%"))

    if item_type:
        normalized_item_type = item_type.strip().lower()

        if normalized_item_type in {"product", "service"}:
            stmt = (
                stmt
                .join(SaleItem, SaleItem.sale_id == Sale.id)
                .where(SaleItem.item_type == normalized_item_type)
                .distinct()
            )

    stmt = (
        stmt
        .order_by(Sale.created_at.desc(), Sale.id.desc())
        .offset(offset)
        .limit(limit)
    )

    return list(db.execute(stmt).scalars().all())
