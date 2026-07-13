from sqlalchemy.orm import Session

from app.models.download_entitlement import DownloadEntitlement


class DownloadEntitlementRepository:
    """Database access for product download entitlements."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_token(self, download_token: str) -> DownloadEntitlement | None:
        return (
            self.db.query(DownloadEntitlement)
            .filter(DownloadEntitlement.download_token == download_token)
            .one_or_none()
        )

    def get_by_sale_item_id(self, sale_item_id: int) -> DownloadEntitlement | None:
        return (
            self.db.query(DownloadEntitlement)
            .filter(DownloadEntitlement.sale_item_id == sale_item_id)
            .one_or_none()
        )

    def create(self, entitlement: DownloadEntitlement) -> DownloadEntitlement:
        self.db.add(entitlement)
        self.db.flush()
        return entitlement
