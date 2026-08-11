from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.purchase_email_delivery import PurchaseEmailDelivery
from app.models.sale import Sale
from app.models.sale_item import SaleItem


def get_delivery_for_update(
    db: Session,
    *,
    delivery_id: int,
) -> PurchaseEmailDelivery | None:
    stmt = (
        select(PurchaseEmailDelivery)
        .where(PurchaseEmailDelivery.id == delivery_id)
        .with_for_update()
    )
    return db.execute(stmt).scalar_one_or_none()


def get_delivery_by_sale_id_for_update(
    db: Session,
    *,
    sale_id: int,
) -> PurchaseEmailDelivery | None:
    stmt = (
        select(PurchaseEmailDelivery)
        .where(PurchaseEmailDelivery.sale_id == sale_id)
        .with_for_update()
    )
    return db.execute(stmt).scalar_one_or_none()


def get_delivery_with_fulfillment(
    db: Session,
    *,
    delivery_id: int,
) -> PurchaseEmailDelivery | None:
    sale_path = joinedload(PurchaseEmailDelivery.sale)
    stmt = (
        select(PurchaseEmailDelivery)
        .options(
            sale_path.selectinload(Sale.items).joinedload(
                SaleItem.download_entitlement
            ),
            sale_path.selectinload(Sale.items).joinedload(
                SaleItem.consultation_entitlement
            ),
        )
        .where(PurchaseEmailDelivery.id == delivery_id)
    )
    return db.execute(stmt).scalars().unique().one_or_none()
