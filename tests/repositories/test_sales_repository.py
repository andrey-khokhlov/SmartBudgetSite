from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.models.enums import PaymentStatus
from app.models.purchase_email_delivery import PurchaseEmailDelivery
from app.models.sale import Sale
from app.repositories.sales_repository import get_sale_for_payment_reconciliation


@pytest.mark.parametrize("with_delivery", [False, True])
def test_get_sale_for_payment_reconciliation_loads_optional_delivery(
    db_session,
    with_delivery,
):
    sale = Sale(
        customer_email="buyer@example.com",
        amount=Decimal("50.00"),
        currency="RUB",
        payment_provider="lava_top",
        payment_status=PaymentStatus.PENDING,
        external_payment_id=f"invoice-optional-delivery-{with_delivery}",
    )
    if with_delivery:
        sale.purchase_email_delivery = PurchaseEmailDelivery()
    db_session.add(sale)
    db_session.commit()
    sale_id = sale.id
    db_session.expunge_all()

    result = get_sale_for_payment_reconciliation(
        db_session,
        payment_provider="lava_top",
        external_payment_id=f"invoice-optional-delivery-{with_delivery}",
    )

    assert result is not None
    assert result.id == sale_id
    assert "purchase_email_delivery" not in inspect(result).unloaded
    if with_delivery:
        assert result.purchase_email_delivery is not None
        assert result.purchase_email_delivery.sale_id == sale_id
    else:
        assert result.purchase_email_delivery is None


def test_get_sale_for_payment_reconciliation_locks_only_sale_select():
    db = Mock(spec=Session)
    expected_sale = object()
    db.execute.return_value.scalars.return_value.unique.return_value.one_or_none.return_value = (
        expected_sale
    )

    result = get_sale_for_payment_reconciliation(
        db,
        payment_provider="lava_top",
        external_payment_id="invoice-lock-shape",
    )

    assert result is expected_sale
    stmt = db.execute.call_args.args[0]
    sql = str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    locked_select = " ".join(sql.split()).upper()
    assert locked_select.endswith("FOR UPDATE")
    assert "JOIN PURCHASE_EMAIL_DELIVERIES" not in locked_select
