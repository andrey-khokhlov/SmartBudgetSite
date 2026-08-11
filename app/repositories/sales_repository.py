from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.enums import PaymentStatus
from app.models.sale import Sale
from app.models.sale_item import SaleItem

STALE_PENDING_AFTER = timedelta(hours=24)


def list_paid_product_purchases_for_email(
    db: Session,
    email: str,
) -> list[SaleItem]:
    stmt = (
        select(SaleItem)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .options(joinedload(SaleItem.product))
        .where(
            Sale.customer_email == email,
            Sale.payment_status == PaymentStatus.PAID,
            SaleItem.item_type == "product",
            SaleItem.product_id.is_not(None),
        )
        .order_by(Sale.created_at.asc(), SaleItem.id.asc())
    )

    return list(db.execute(stmt).scalars().all())


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
        .options(
            selectinload(Sale.items),
            joinedload(Sale.purchase_email_delivery),
        )
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


def get_sale_for_payment_reconciliation(
    db: Session,
    *,
    payment_provider: str,
    external_payment_id: str,
) -> Sale | None:
    """Resolve and lock one provider-owned Sale for payment reconciliation."""

    stmt = (
        select(Sale)
        .options(
            selectinload(Sale.items).joinedload(SaleItem.service_addon),
            selectinload(Sale.items).joinedload(SaleItem.consultation_entitlement),
            selectinload(Sale.items).joinedload(SaleItem.download_entitlement),
            selectinload(Sale.purchase_email_delivery),
        )
        .where(
            Sale.payment_provider == payment_provider,
            Sale.external_payment_id == external_payment_id,
        )
        .with_for_update()
    )
    return db.execute(stmt).scalars().unique().one_or_none()


def stale_pending_sale_ids(
    sales: list[Sale],
    *,
    now: datetime | None = None,
) -> set[int]:
    """Derive the operator warning for pending Sales older than 24 hours."""

    current_time = now or datetime.now(UTC)
    stale_before = current_time - STALE_PENDING_AFTER
    result: set[int] = set()
    for sale in sales:
        created_at = sale.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        if sale.payment_status == PaymentStatus.PENDING and created_at <= stale_before:
            result.add(sale.id)
    return result
