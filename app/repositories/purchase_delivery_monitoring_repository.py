from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.consultation_entitlement import ConsultationEntitlement
from app.models.download_entitlement import DownloadEntitlement
from app.models.enums import PaymentStatus
from app.models.purchase_delivery_incident import PurchaseDeliveryIncident
from app.models.purchase_email_delivery import PurchaseEmailDelivery
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.service_addon import ServiceAddon


def lock_incident_writes(db: Session) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.connection(execution_options={"isolation_level": "READ COMMITTED"})
        db.execute(
            text("LOCK TABLE purchase_delivery_incidents IN SHARE ROW EXCLUSIVE MODE")
        )
    elif db.get_bind().dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    else:
        raise RuntimeError("Unsupported database for purchase delivery monitoring.")


def read_paid_fulfillment(db: Session):
    # Read the complete commerce snapshot in one statement and select only
    # fields used by the rules.
    statement = (
        select(
            Sale.id.label("sale_id"),
            SaleItem.id.label("item_id"),
            SaleItem.item_type,
            SaleItem.product_release_id,
            ServiceAddon.service_type,
            DownloadEntitlement.release_id.label("download_release_id"),
            ConsultationEntitlement.id.label("consultation_id"),
            PurchaseEmailDelivery.status.label("email_status"),
            PurchaseEmailDelivery.created_at.label("email_created_at"),
            PurchaseEmailDelivery.sending_started_at,
        )
        .select_from(Sale)
        .outerjoin(Sale.items)
        .outerjoin(SaleItem.service_addon)
        .outerjoin(SaleItem.download_entitlement)
        .outerjoin(SaleItem.consultation_entitlement)
        .outerjoin(Sale.purchase_email_delivery)
        .where(Sale.payment_status == PaymentStatus.PAID)
        .order_by(Sale.id, SaleItem.id)
    )
    return db.execute(statement)


def read_open_incidents(db: Session):
    return db.scalars(
        select(PurchaseDeliveryIncident).where(
            PurchaseDeliveryIncident.resolved_at.is_(None)
        )
    )
