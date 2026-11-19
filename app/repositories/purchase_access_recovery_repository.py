from sqlalchemy import Exists, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.models.purchase_access_recovery import PurchaseAccessRecovery


def recovery_exists_for_sale(sale_id: int | InstrumentedAttribute[int]) -> Exists:
    return (
        select(PurchaseAccessRecovery.id)
        .where(PurchaseAccessRecovery.sale_id == sale_id)
        .exists()
    )


def recovery_for_request(
    db: Session, sale_id: int, request_id: str
) -> PurchaseAccessRecovery | None:
    return db.scalar(
        select(PurchaseAccessRecovery).where(
            PurchaseAccessRecovery.sale_id == sale_id,
            PurchaseAccessRecovery.request_id == request_id,
        )
    )


def latest_recovery(
    db: Session, sale_id: int, *, for_update: bool = False
) -> PurchaseAccessRecovery | None:
    statement = (
        select(PurchaseAccessRecovery)
        .where(PurchaseAccessRecovery.sale_id == sale_id)
        .order_by(PurchaseAccessRecovery.id.desc())
        .limit(1)
    )
    if for_update:
        statement = statement.with_for_update().execution_options(
            populate_existing=True
        )
    return db.scalar(statement)


def lock_recovery(db: Session, recovery_id: int) -> PurchaseAccessRecovery | None:
    return db.scalar(
        select(PurchaseAccessRecovery)
        .where(PurchaseAccessRecovery.id == recovery_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
