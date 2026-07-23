import hashlib
import hmac
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.sale_item import SaleItem
from app.repositories.sales_repository import list_paid_product_purchases_for_email


@dataclass(frozen=True)
class VerifiedProductPurchase:
    purchase_reference: str
    product_name: str
    edition: str


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _purchase_reference(sale_item_id: int) -> str:
    digest = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        f"feedback-purchase:v1:{sale_item_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"FP-{digest}"


def _paid_product_purchases(db: Session, email: str) -> list[SaleItem]:
    normalized_email = _normalize_email(email)
    if not normalized_email:
        return []

    return list_paid_product_purchases_for_email(
        db=db,
        email=normalized_email,
    )


def list_verified_product_purchases(
    db: Session,
    email: str,
) -> list[VerifiedProductPurchase]:
    purchases = _paid_product_purchases(db, email)
    return [
        VerifiedProductPurchase(
            purchase_reference=_purchase_reference(item.id),
            product_name=item.product.name,
            edition=item.product.edition,
        )
        for item in purchases
    ]


def resolve_verified_product_id(
    db: Session,
    *,
    email: str,
    purchase_reference: str | None,
) -> int:
    purchases = _paid_product_purchases(db, email)
    if not purchases:
        raise HTTPException(
            status_code=400,
            detail="No verified product purchase found",
        )

    if not purchase_reference:
        raise HTTPException(
            status_code=400,
            detail="Purchase reference is required for product feedback",
        )

    for item in purchases:
        if hmac.compare_digest(
            _purchase_reference(item.id),
            purchase_reference,
        ):
            product_id = item.product_id
            if product_id is not None:
                return product_id

    raise HTTPException(
        status_code=400,
        detail="Invalid purchase reference",
    )
