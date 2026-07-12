from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.enums import PaymentStatus
from app.models.sale import Sale


def make_sale(*, provider: str, external_id: str | None, status: str) -> Sale:
    return Sale(
        customer_email="customer@example.com",
        amount=Decimal("39.00"),
        currency="EUR",
        payment_provider=provider,
        external_payment_id=external_id,
        payment_status=status,
    )


def test_failed_sale_may_have_null_external_payment_id(db_session):
    sale = make_sale(
        provider="stripe",
        external_id=None,
        status=PaymentStatus.FAILED,
    )
    db_session.add(sale)
    db_session.commit()
    assert sale.id is not None
    assert sale.external_payment_id is None


def test_duplicate_provider_external_payment_id_is_rejected(db_session):
    db_session.add_all(
        [
            make_sale(provider="stripe", external_id="cs_test_same", status=PaymentStatus.PENDING),
            make_sale(provider="stripe", external_id="cs_test_same", status=PaymentStatus.PENDING),
        ]
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_same_external_payment_id_is_allowed_for_different_providers(db_session):
    db_session.add_all(
        [
            make_sale(provider="stripe", external_id="shared-id", status=PaymentStatus.PENDING),
            make_sale(provider="other", external_id="shared-id", status=PaymentStatus.PENDING),
        ]
    )
    db_session.commit()


def test_multiple_null_external_payment_ids_are_allowed(db_session):
    db_session.add_all(
        [
            make_sale(provider="stripe", external_id=None, status=PaymentStatus.FAILED),
            make_sale(provider="stripe", external_id=None, status=PaymentStatus.FAILED),
        ]
    )
    db_session.commit()
