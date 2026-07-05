from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.enums import PaymentStatus, SaleItemType
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem


def create_product_sale(
    db: Session,
    *,
    product: Product,
    customer_email: str,
    amount: Decimal,
    currency: str,
    payment_provider: str | None = None,
    external_payment_id: str | None = None,
    payment_status: str = PaymentStatus.PENDING,
) -> Sale:
    """
    Create sale header with one product sale item.

    Business rules:
    - Sale is the order header.
    - Product purchase must create exactly one product SaleItem.
    - SaleItem stores a historical pricing snapshot.

    Side effects:
    - Adds Sale and SaleItem to the current DB session.
    - Flushes the session to assign sale.id.

    Invariants / restrictions:
    - This function does not commit.
    - Caller controls transaction boundaries.
    """

    sale = Sale(
        product_id=product.id,  # temporary legacy compatibility
        customer_email=customer_email,
        amount=amount,
        currency=currency,
        payment_provider=payment_provider,
        payment_status=payment_status,
        external_payment_id=external_payment_id,
    )
    db.add(sale)
    db.flush()

    sale_item = SaleItem(
        sale_id=sale.id,
        item_type=SaleItemType.PRODUCT,
        product_id=product.id,
        item_name=f"{product.name} {product.edition}",
        currency_code=currency,
        amount=amount,
        quantity=1,
    )
    db.add(sale_item)

    return sale


def create_service_sale_item(
    *,
    sale: Sale,
    service_addon_id: int,
    item_name: str,
    currency_code: str,
    amount: Decimal,
    quantity: int = 1,
) -> SaleItem:
    """
    Create service sale item for an existing sale.

    Business rules:
    - Service items belong to an existing sale.
    - Service items are immutable pricing snapshots.
    - Service items must reference service_addon_id.

    Side effects:
    - None. Caller is responsible for adding item to DB session.

    Invariants / restrictions:
    - Does not commit.
    """

    return SaleItem(
        sale_id=sale.id,
        item_type=SaleItemType.SERVICE,
        product_id=None,
        service_addon_id=service_addon_id,
        item_name=item_name,
        currency_code=currency_code,
        amount=amount,
        quantity=quantity,
    )


def calculate_sale_total(items: list[SaleItem]) -> Decimal:
    """
    Calculate sale total from sale items.

    Business rules:
    - Sale total must be derived from item snapshots.
    - All items must use the same currency.

    Side effects:
    - None.

    Invariants / restrictions:
    - Empty item list is not allowed.
    - Mixed currencies are not allowed.
    """

    if not items:
        raise ValueError("Sale must contain at least one item.")

    currencies = {item.currency_code for item in items}

    if len(currencies) != 1:
        raise ValueError("Sale items must use the same currency.")

    return sum(
        (item.amount * item.quantity for item in items),
        start=Decimal("0.00"),
    )


def create_standalone_service_sale(
    db: Session,
    *,
    service_addon_id: int,
    service_name: str,
    customer_email: str,
    amount: Decimal,
    currency: str,
    payment_provider: str | None = None,
    external_payment_id: str | None = None,
    payment_status: str = PaymentStatus.PENDING,
) -> Sale:
    """
    Create sale header with one standalone service sale item.

    Business rules:
    - Standalone service sale has no product_id.
    - Service purchase must create exactly one service SaleItem.
    - SaleItem stores a historical pricing snapshot.

    Side effects:
    - Adds Sale and SaleItem to the current DB session.
    - Flushes the session to assign sale.id.

    Invariants / restrictions:
    - This function does not commit.
    - Caller controls transaction boundaries.
    """

    sale = Sale(
        product_id=None,
        customer_email=customer_email,
        amount=amount,
        currency=currency,
        payment_provider=payment_provider,
        payment_status=payment_status,
        external_payment_id=external_payment_id,
    )
    db.add(sale)
    db.flush()

    sale_item = SaleItem(
        sale_id=sale.id,
        item_type="service",
        product_id=None,
        service_addon_id=service_addon_id,
        item_name=service_name,
        currency_code=currency,
        amount=amount,
        quantity=1,
    )
    db.add(sale_item)

    return sale