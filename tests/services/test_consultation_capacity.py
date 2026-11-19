from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.consultation_cancellation import ConsultationCancellation
from app.models.consultation_capacity import ConsultationCapacityState
from app.models.consultation_entitlement import ConsultationEntitlement
from app.models.enums import PaymentStatus
from app.models.product_release import ProductRelease
from app.models.sale import Sale
from app.models.service_addon import ServiceAddon
from app.schemas.webhooks import NormalizedPaymentEvent, PaymentOutcome
from app.services import consultation_capacity_service as capacity
from app.services.consultation_entitlement_service import (
    create_consultation_entitlement,
)
from app.services.lava_top.client import LavaTopInvoice
from app.services.payment_provider_offer_service import set_lava_top_standalone_offer
from app.services.payment_reconciliation_service import (
    PaymentReconciliationResult,
    reconcile_payment_event,
)
from app.services.payment_service import (
    initiate_lava_top_standalone_consultation_checkout,
)
from app.services.sale_service import (
    create_product_sale,
    create_service_sale_item,
    create_standalone_service_sale,
)
from tests.services.test_standalone_consultation_payment import add_offer, start
from tests.web.test_checkout_initiation import create_checkout_catalog


def add_available_rights(db, count, offer_id=None):
    if offer_id is None:
        offer_id = add_offer(db, "EUR", code="capacity-fixture", is_active=False)
    offer = db.get(ServiceAddon, offer_id)
    rights = []
    for _ in range(count):
        sale = create_standalone_service_sale(
            db,
            service_addon_id=offer.id,
            service_name=offer.name,
            customer_email="buyer@example.com",
            amount=offer.amount,
            currency=offer.currency_code,
            payment_status=PaymentStatus.PAID,
        )
        db.flush()
        rights.append(create_consultation_entitlement(db, sale_item=sale.items[0]))
    db.commit()
    return rights


@pytest.mark.parametrize("count", [0, 2, 3, 4, 5])
def test_capacity_boundaries(db_session, count):
    add_available_rights(db_session, count)
    snapshot = capacity.get_consultation_capacity(db_session)
    assert (snapshot.outstanding, snapshot.warning_threshold, snapshot.limit) == (
        count,
        3,
        4,
    )
    assert snapshot.available == (count < 4)


def test_workload_formula_counts_current_rights_across_sales_modes(db_session):
    db = db_session
    now = datetime.now(UTC)
    rub = add_offer(db, "RUB")
    eur = add_offer(
        db, "EUR", code="historical-eur-addon", usage_type="addon", is_active=False
    )
    support = add_offer(db, "EUR", code="support", service_type="support")
    product = create_checkout_catalog(db, slug="smartbudget-int-standard-capacity-test")
    sale = create_product_sale(
        db,
        product=product,
        product_release=db.query(ProductRelease).filter_by(product_id=product.id).one(),
        customer_email="bundle@example.com",
        amount=Decimal("39.00"),
        currency="EUR",
        payment_status=PaymentStatus.PAID,
    )
    db.flush()
    addon = create_service_sale_item(
        sale=sale,
        service_addon_id=eur,
        item_name="Consultation",
        currency_code="EUR",
        amount=Decimal("69.00"),
    )
    db.add(addon)
    db.flush()
    sale.amount += addon.amount
    create_consultation_entitlement(db, sale_item=addon)
    db.commit()
    (
        valid,
        booked,
        expired_status,
        cancelled,
        expired_time,
        exact,
        closing,
        refunded,
        pending,
    ) = add_available_rights(db, 9, rub)
    booked.status = "booked"
    expired_status.status = "expired"
    cancelled.status = "cancelled"
    expired_time.expires_at = now - timedelta(seconds=1)
    exact.expires_at = now
    db.add(ConsultationCancellation(entitlement_id=closing.id, access_closed_at=now))
    refunded.sale_item.sale.payment_status = PaymentStatus.REFUNDED
    pending.sale_item.sale.payment_status = PaymentStatus.PENDING
    support_sale = create_standalone_service_sale(
        db,
        service_addon_id=support,
        service_name="Support",
        customer_email="support@example.com",
        amount=Decimal("30"),
        currency="EUR",
        payment_status=PaymentStatus.PAID,
    )
    db.flush()
    db.add(
        ConsultationEntitlement(
            sale_item_id=support_sale.items[0].id, expires_at=now + timedelta(days=1)
        )
    )
    db.commit()
    assert capacity.get_consultation_capacity(db, now=now).outstanding == 2
    assert valid.status == expired_time.status == "available"


def test_manual_suspension_persists_and_resume_still_respects_limit(db_session):
    rights = add_available_rights(db_session, 4)
    engine = db_session.get_bind()
    with Session(engine) as window:
        capacity.set_consultation_sales_suspended(window, suspended=True)
    rights[0].status = "booked"
    db_session.commit()
    with Session(engine) as restarted:
        snapshot = capacity.get_consultation_capacity(restarted)
        assert snapshot.outstanding == 3
        assert snapshot.manually_suspended
        assert not snapshot.available
    with Session(engine) as window:
        capacity.set_consultation_sales_suspended(window, suspended=False)
    assert capacity.consultation_sales_available(db_session)
    rights[0].status = "available"
    db_session.commit()
    assert not capacity.consultation_sales_available(db_session)


@pytest.mark.parametrize("unreadable", [False, True])
def test_required_state_failure_cannot_start_checkout(
    db_session, monkeypatch, unreadable
):
    offer = add_offer(db_session)
    if unreadable:
        monkeypatch.setattr(
            capacity, "read_capacity", Mock(side_effect=SQLAlchemyError("read error"))
        )
    else:
        db_session.delete(db_session.get(ConsultationCapacityState, 1))
        db_session.commit()
    invoice = Mock()
    monkeypatch.setattr("app.services.payment_service.create_invoice", invoice)
    with pytest.raises(capacity.ConsultationCapacityUnavailableError):
        start(db_session, offer)
    invoice.assert_not_called()
    assert db_session.query(Sale).count() == 0


def test_payment_started_before_exhaustion_still_fulfills(db_session, monkeypatch):
    db = db_session
    offer = add_offer(db, "RUB")
    set_lava_top_standalone_offer(
        db, service_addon_id=offer, external_offer_id="test-offer"
    )
    invoice = Mock(
        return_value=LavaTopInvoice("before-capacity", "https://pay.example")
    )
    monkeypatch.setattr("app.services.payment_service.create_invoice", invoice)
    start(db, offer)
    assert capacity.get_consultation_capacity(db).outstanding == 0
    add_available_rights(db, 4, offer)

    with pytest.raises(capacity.ConsultationCapacityUnavailableError):
        initiate_lava_top_standalone_consultation_checkout(
            db,
            service_addon_id=offer,
            currency="RUB",
            customer_email="next@example.com",
        )
    invoice.assert_called_once()
    assert db.query(Sale).count() == 5

    event = NormalizedPaymentEvent(
        provider="lava_top",
        external_payment_id="before-capacity",
        outcome=PaymentOutcome.SUCCESS,
        amount=Decimal("6123.45"),
        currency="RUB",
    )
    assert (
        reconcile_payment_event(db, event).result == PaymentReconciliationResult.APPLIED
    )
    db.commit()
    assert capacity.get_consultation_capacity(db).outstanding == 5
    sale = db.query(Sale).filter_by(external_payment_id="before-capacity").one()
    entitlement = sale.items[0].consultation_entitlement
    assert sale.payment_status == PaymentStatus.PAID
    assert entitlement.status == "available" and entitlement.booking_token
