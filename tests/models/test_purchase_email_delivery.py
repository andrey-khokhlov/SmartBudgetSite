from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.enums import PaymentStatus
from app.models.purchase_email_delivery import (
    PurchaseEmailDelivery,
    PurchaseEmailDeliveryStatus,
)
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.service_addon import ServiceAddon


def make_sale(email: str = "customer@example.com") -> Sale:
    return Sale(
        customer_email=email,
        amount=Decimal("39.00"),
        currency="EUR",
        payment_status=PaymentStatus.PAID,
    )


def test_purchase_email_delivery_persists_with_defaults_and_relationships(db_session):
    sale = make_sale()
    delivery = PurchaseEmailDelivery(sale=sale)
    db_session.add(delivery)
    db_session.commit()

    assert delivery.id is not None
    assert delivery.sale_id == sale.id
    assert delivery.status == PurchaseEmailDeliveryStatus.PENDING.value
    assert delivery.attempt_count == 0
    assert delivery.created_at is not None
    assert delivery.updated_at is not None
    assert sale.purchase_email_delivery is delivery
    assert delivery.sale is sale
    assert PurchaseEmailDelivery.__table__.c.status.type.length == 32


def test_only_one_purchase_email_delivery_is_allowed_per_sale(db_session):
    sale = make_sale()
    db_session.add(sale)
    db_session.flush()
    db_session.add_all(
        [
            PurchaseEmailDelivery(sale_id=sale.id),
            PurchaseEmailDelivery(sale_id=sale.id),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_invalid_purchase_email_delivery_status_is_rejected(db_session):
    sale = make_sale()
    db_session.add(sale)
    db_session.flush()
    db_session.add(PurchaseEmailDelivery(sale_id=sale.id, status="unknown"))

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_negative_purchase_email_attempt_count_is_rejected(db_session):
    sale = make_sale()
    db_session.add(sale)
    db_session.flush()
    db_session.add(PurchaseEmailDelivery(sale_id=sale.id, attempt_count=-1))

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_purchase_email_delivery_does_not_change_sale_item_behavior(db_session):
    service = ServiceAddon(
        code="purchase_email_delivery_consultation",
        name="1:1 consultation",
        service_type="consultation",
        usage_type="standalone",
        family_slug="smartbudget",
        package_code="INT",
        currency_code="EUR",
        amount=Decimal("39.00"),
        is_active=True,
    )
    sale = make_sale()
    item = SaleItem(
        sale=sale,
        item_type="service",
        service_addon=service,
        item_name="1:1 consultation",
        currency_code="EUR",
        amount=Decimal("39.00"),
        quantity=1,
    )
    delivery = PurchaseEmailDelivery(sale=sale)
    db_session.add_all([item, delivery])
    db_session.commit()

    assert sale.items == [item]
    assert item.sale is sale
    assert sale.purchase_email_delivery is delivery
