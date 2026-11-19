from sqlalchemy.orm import Session

from app.models.download_entitlement import DownloadEntitlement


class DownloadEntitlementRepository:
    """Database access for product download entitlements."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_token(
        self, download_token: str, *, for_update: bool = False
    ) -> DownloadEntitlement | None:
        query = self.db.query(DownloadEntitlement).filter(
            DownloadEntitlement.download_token == download_token
        )
        if for_update:
            query = query.with_for_update().populate_existing()
        return query.one_or_none()

    def get_by_support_reference(
        self,
        support_reference: str,
    ) -> DownloadEntitlement | None:
        return (
            self.db.query(DownloadEntitlement)
            .filter(DownloadEntitlement.support_reference == support_reference)
            .one_or_none()
        )

    def get_by_sale_item_id(
        self, sale_item_id: int, *, for_update: bool = False
    ) -> DownloadEntitlement | None:
        query = self.db.query(DownloadEntitlement).filter(
            DownloadEntitlement.sale_item_id == sale_item_id
        )
        if for_update:
            query = query.with_for_update().populate_existing()
        return query.one_or_none()

    def create(self, entitlement: DownloadEntitlement) -> DownloadEntitlement:
        self.db.add(entitlement)
        self.db.flush()
        return entitlement
