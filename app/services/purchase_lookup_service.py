from sqlalchemy.orm import Session

from app.repositories.sales_repository import has_paid_product_purchase_for_email


def has_verified_product_purchase(db: Session, email: str) -> bool:
    normalized_email = email.strip().lower()
    if not normalized_email:
        return False

    return has_paid_product_purchase_for_email(
        db=db,
        email=normalized_email,
    )
