from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.product import Product
from app.models.product_release import ProductRelease


def product_lock_for_release_statement(release_id: int) -> Select:
    return (
        select(Product)
        .join(ProductRelease, ProductRelease.product_id == Product.id)
        .where(ProductRelease.id == release_id)
        .with_for_update(of=Product)
    )


class ProductReleaseRepository:
    """
    Repository for ProductRelease entity.

    Handles DB access for product release management.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_by_product_id(self, product_id: int) -> list[ProductRelease]:
        return (
            self.db.query(ProductRelease)
            .filter(ProductRelease.product_id == product_id)
            .order_by(ProductRelease.created_at.desc(), ProductRelease.id.desc())
            .all()
        )

    def get_by_id(self, release_id: int) -> ProductRelease | None:
        return (
            self.db.query(ProductRelease)
            .filter(ProductRelease.id == release_id)
            .first()
        )

    def lock_product_for_release(self, release_id: int) -> Product | None:
        """Serialize publication by locking the release's owning product row."""
        return self.db.scalars(product_lock_for_release_statement(release_id)).first()

    def list_by_product_id_for_update(
        self,
        product_id: int,
    ) -> list[ProductRelease]:
        return (
            self.db.query(ProductRelease)
            .filter(ProductRelease.product_id == product_id)
            .order_by(ProductRelease.created_at.desc(), ProductRelease.id.desc())
            .with_for_update()
            .all()
        )

    def get_active_by_product_id(self, product_id: int) -> ProductRelease | None:
        return (
            self.db.query(ProductRelease)
            .filter(ProductRelease.product_id == product_id)
            .filter(ProductRelease.is_active.is_(True))
            .first()
        )

    def get_by_product_id_and_version(
        self,
        product_id: int,
        version: str,
    ) -> ProductRelease | None:
        return (
            self.db.query(ProductRelease)
            .filter(ProductRelease.product_id == product_id)
            .filter(ProductRelease.version == version)
            .first()
        )

    def get_by_storage_key(self, storage_key: str) -> ProductRelease | None:
        return (
            self.db.query(ProductRelease)
            .filter(ProductRelease.storage_key == storage_key)
            .first()
        )

    def list_all(self) -> list[ProductRelease]:
        return self.db.query(ProductRelease).order_by(ProductRelease.id.asc()).all()

    def create(self, release: ProductRelease) -> ProductRelease:
        self.db.add(release)
        self.db.flush()
        return release
