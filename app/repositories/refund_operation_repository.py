from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.consultation_cancellation import ConsultationCancellation
from app.models.consultation_entitlement import ConsultationEntitlement
from app.models.download_entitlement import DownloadEntitlement
from app.models.refund_operation import RefundOperation
from app.models.sale import Sale
from app.models.sale_item import SaleItem


class RefundOperationRepository:
    """Database access for full-refund workflows."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_sale_id(self, sale_id: int) -> RefundOperation | None:
        return self.db.execute(
            select(RefundOperation).where(RefundOperation.sale_id == sale_id)
        ).scalar_one_or_none()

    def get_sale_for_admin(self, sale_id: int) -> Sale | None:
        return (
            self.db.execute(
                select(Sale)
                .options(
                    selectinload(Sale.items)
                    .joinedload(SaleItem.consultation_entitlement)
                    .joinedload(ConsultationEntitlement.cancellation),
                    selectinload(Sale.items).joinedload(SaleItem.service_addon),
                    selectinload(Sale.items).joinedload(SaleItem.download_entitlement),
                    joinedload(Sale.refund_operation),
                    joinedload(Sale.purchase_email_delivery),
                )
                .where(Sale.id == sale_id)
            )
            .scalars()
            .unique()
            .one_or_none()
        )

    def lock_sale(self, sale_id: int) -> Sale | None:
        return self.db.execute(
            select(Sale)
            .where(Sale.id == sale_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()

    def lock_by_sale_id(self, sale_id: int) -> RefundOperation | None:
        return self.db.execute(
            select(RefundOperation)
            .where(RefundOperation.sale_id == sale_id)
            .with_for_update()
        ).scalar_one_or_none()

    def lock_download_entitlements(self, sale_id: int) -> list[DownloadEntitlement]:
        return list(
            self.db.execute(
                select(DownloadEntitlement)
                .join(SaleItem, SaleItem.id == DownloadEntitlement.sale_item_id)
                .where(SaleItem.sale_id == sale_id)
                .order_by(DownloadEntitlement.id)
                .with_for_update()
            ).scalars()
        )

    def lock_consultation_entitlements(
        self, sale_id: int
    ) -> list[ConsultationEntitlement]:
        return list(
            self.db.execute(
                select(ConsultationEntitlement)
                .join(SaleItem, SaleItem.id == ConsultationEntitlement.sale_item_id)
                .where(SaleItem.sale_id == sale_id)
                .order_by(ConsultationEntitlement.id)
                .with_for_update()
            ).scalars()
        )

    def verified_consultation_ids(self, sale_id: int) -> list[int]:
        return list(self.db.scalars(
            select(ConsultationCancellation.entitlement_id)
            .join(ConsultationEntitlement, ConsultationEntitlement.id == ConsultationCancellation.entitlement_id)
            .join(SaleItem, SaleItem.id == ConsultationEntitlement.sale_item_id)
            .join(RefundOperation, RefundOperation.sale_id == SaleItem.sale_id)
            .where(
                SaleItem.sale_id == sale_id,
                RefundOperation.status == "pending",
                ConsultationCancellation.verified_at.is_not(None),
            )
            .order_by(ConsultationCancellation.entitlement_id)
        ))

    def create(self, operation: RefundOperation) -> RefundOperation:
        self.db.add(operation)
        self.db.flush()
        return operation
