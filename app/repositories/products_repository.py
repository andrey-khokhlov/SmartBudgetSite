from __future__ import annotations
from sqlalchemy.orm import Session
from app.models.product import Product
from sqlalchemy import and_, or_
from app.models.product_price import ProductPrice


class ProductsRepository:
    """
    Repository for Product entity.

    Handles DB access for admin product management.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_products(self):
        result = (
            self.db.query(Product, ProductPrice)
            .outerjoin(
                ProductPrice,
                and_(
                    ProductPrice.product_id == Product.id,
                    ProductPrice.is_active == True,
                    ProductPrice.currency_code.in_(["RUB", "EUR"]),
                ),
            )
            .order_by(Product.id.desc())
            .all()
        )

        return result

    def get_by_slug(self, slug: str) -> Product | None:
        """Return the product whose unique slug exactly matches the input."""
        return self.db.query(Product).filter(Product.slug == slug).one_or_none()

    def get_active_price_by_product_and_currency(
        self,
        *,
        product_id: int,
        currency_code: str,
    ) -> ProductPrice | None:
        """Return the active catalog price for one product and currency."""
        return (
            self.db.query(ProductPrice)
            .filter(
                ProductPrice.product_id == product_id,
                ProductPrice.currency_code == currency_code,
                ProductPrice.is_active.is_(True),
            )
            .one_or_none()
        )

    def get_product_with_active_price_by_slug(self, slug: str):
        """
        Fetch product and its active price by slug.

        Business rules:
        - Product is identified by unique slug (SKU).
        - Only active price should be returned.

        Side effects:
        - None (read-only query).

        Invariants / restrictions:
        - At most one active price per (product_id, currency_code).
        """

        result = (
            self.db.query(Product, ProductPrice)
            .outerjoin(
                ProductPrice,
                and_(
                    ProductPrice.product_id == Product.id,
                    ProductPrice.is_active.is_(True),
                ),
            )
            .filter(Product.slug == slug)
            .one_or_none()
        )

        if result is None:
            return None, None

        product, price = result
        return product, price

    def list_products_by_family_slug(self, family_slug: str):
        """
        Fetch products available for purchase by product family with active prices.

        Business rules:
        - family_slug groups related product SKUs, for example SmartBudget RU/INT variants.
        - Only products with status 'in_sale' are shown on the buy selection page.
        - Only active prices are returned.

        Side effects:
        - None (read-only query).

        Invariants / restrictions:
        - Does not include discontinued or in-development products.
        - Does not create sales or payment records.
        """

        result = (
            self.db.query(Product, ProductPrice)
            .outerjoin(
                ProductPrice,
                and_(
                    ProductPrice.product_id == Product.id,
                    ProductPrice.is_active.is_(True),
                ),
            )
            .filter(Product.family_slug == family_slug)
            .filter(Product.status == "in_sale")
            .order_by(Product.name.asc(), Product.edition.asc(), Product.slug.asc())
            .all()
        )

        return result
