from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError

from app.models.enums import PaymentStatus
from app.models.product import Product
from app.models.product_release import ProductRelease
from app.models.purchase_delivery_incident import PurchaseDeliveryIncident
from app.models.purchase_email_delivery import PurchaseEmailDelivery
from app.models.sale import Sale
from app.models.service_addon import ServiceAddon
from app.schemas.webhooks import NormalizedPaymentEvent, PaymentOutcome
from app.services.payment_reconciliation_service import reconcile_payment_event
from app.services.purchase_delivery_monitoring_service import scan_purchase_delivery
from app.services.sale_service import (
    create_product_sale,
    create_service_sale_item,
    create_standalone_service_sale,
)

NOW = datetime(2026, 11, 12, 12, tzinfo=UTC)
BUYER_EMAIL = "private-buyer@example.com"


def create_purchase(db, composition):
    checkout = {
        "customer_email": BUYER_EMAIL,
        "amount": Decimal("50.00"),
        "currency": "RUB",
        "payment_provider": "lava_top",
        "external_payment_id": "monitoring-test-invoice",
    }
    if composition != "consultation":
        product = Product(
            family_slug="smartbudget",
            slug="monitoring-product",
            name="SmartBudget",
            edition="Standard",
            archive_path="archives/smartbudget.zip",
            status="in_sale",
        )
        release = ProductRelease(
            product=product,
            version="1.0",
            storage_provider="cloudflare_r2",
            storage_key="product-releases/monitoring/1.0.zip",
            original_filename="SmartBudget.zip",
            is_active=True,
        )
        db.add(release)
        db.flush()
        sale = create_product_sale(
            db, product=product, product_release=release, **checkout
        )

    if composition != "product":
        addon = ServiceAddon(
            code="monitoring-consultation",
            name="Consultation",
            service_type="consultation",
            usage_type="standalone" if composition == "consultation" else "addon",
            family_slug="smartbudget",
            package_code="RU",
            currency_code="RUB",
            amount=Decimal("50.00"),
            is_active=True,
        )
        db.add(addon)
        db.flush()
        if composition == "consultation":
            sale = create_standalone_service_sale(
                db, service_addon_id=addon.id, service_name=addon.name, **checkout
            )
        else:
            db.add(
                create_service_sale_item(
                    sale=sale,
                    service_addon_id=addon.id,
                    item_name=addon.name,
                    currency_code="RUB",
                    amount=Decimal("25.00"),
                )
            )
            sale.amount += Decimal("25.00")

    db.commit()
    sale_id = sale.id
    reconcile_payment_event(
        db,
        NormalizedPaymentEvent(
            provider=sale.payment_provider,
            external_payment_id=sale.external_payment_id,
            outcome=PaymentOutcome.SUCCESS,
            amount=sale.amount,
            currency=sale.currency,
        ),
    )
    sale.purchase_email_delivery.status = "sent"
    db.commit()
    return sale_id


@pytest.mark.parametrize("composition", ["product", "consultation", "bundle"])
def test_complete_purchase(db_session, composition):
    create_purchase(db_session, composition)
    assert scan_purchase_delivery(db_session, now=NOW) == {
        "paid_sales_scanned": 1,
        "open_incidents": 0,
        "opened": 0,
        "resolved": 0,
        "by_kind": {},
        "by_severity": {},
    }


def test_missing_and_inconsistent_fulfillment(db_session):
    sale = db_session.get(Sale, create_purchase(db_session, "bundle"))
    product_item = next(item for item in sale.items if item.item_type == "product")
    consultation_item = next(item for item in sale.items if item.item_type == "service")
    product_item.product_release_id = None
    consultation_item.consultation_entitlement = None
    sale.purchase_email_delivery = None
    db_session.commit()

    summary = scan_purchase_delivery(db_session, now=NOW)
    assert summary["by_kind"] == {
        "item_fulfillment_invalid": 2,
        "email_record_missing": 1,
    }
    assert summary["by_severity"] == {"error": 3}
    assert db_session.scalar(select(PurchaseEmailDelivery.id)) is None
    assert sale.payment_status == PaymentStatus.PAID


@pytest.mark.parametrize("payment_status", [PaymentStatus.PAID, PaymentStatus.PENDING])
def test_sale_without_items_or_email(db_session, payment_status):
    db_session.add(
        Sale(
            customer_email=BUYER_EMAIL,
            amount=50,
            currency="RUB",
            payment_status=payment_status,
        )
    )
    db_session.commit()
    expected = (
        {"sale_items_missing": 1, "email_record_missing": 1}
        if payment_status == PaymentStatus.PAID
        else {}
    )
    assert scan_purchase_delivery(db_session, now=NOW)["by_kind"] == expected


@pytest.mark.parametrize(
    ("status", "kind", "severity"),
    [
        ("failed", "email_failed", "error"),
        ("reconciliation_required", "email_reconciliation_required", "error"),
        ("pending", "email_pending_stalled", "warning"),
        ("sending", "email_sending_stalled", "warning"),
    ],
)
def test_email_rules_and_stall_boundary(db_session, status, kind, severity):
    sale = db_session.get(Sale, create_purchase(db_session, "product"))
    delivery = sale.purchase_email_delivery
    delivery.status = status
    delivery.created_at = NOW - timedelta(days=1) if status == "sending" else NOW
    delivery.sending_started_at = NOW if status == "sending" else None
    delivery.last_attempt_at = (
        NOW + timedelta(minutes=1) if status == "sending" else None
    )
    db_session.commit()

    if severity == "warning":
        before = NOW + timedelta(minutes=5) - timedelta(microseconds=1)
        assert scan_purchase_delivery(db_session, now=before)["open_incidents"] == 0
        observed_at = NOW + timedelta(minutes=5)
    else:
        observed_at = NOW
    result = scan_purchase_delivery(db_session, now=observed_at)
    assert result["by_kind"] == {kind: 1}
    assert result["by_severity"] == {severity: 1}


def test_repeat_resolution_and_recurrence(db_session):
    sale_id = create_purchase(db_session, "product")
    sale = db_session.get(Sale, sale_id)
    sale.purchase_email_delivery.status = "failed"
    db_session.commit()
    assert scan_purchase_delivery(db_session, now=NOW)["opened"] == 1

    second = NOW + timedelta(minutes=1)
    assert scan_purchase_delivery(db_session, now=second)["opened"] == 0
    sale.purchase_email_delivery.status = "sent"
    db_session.commit()
    third = NOW + timedelta(minutes=2)
    assert scan_purchase_delivery(db_session, now=third)["resolved"] == 1

    sale.purchase_email_delivery.status = "failed"
    db_session.commit()
    fourth = NOW + timedelta(minutes=3)
    assert scan_purchase_delivery(db_session, now=fourth)["opened"] == 1

    first, recurring = db_session.scalars(
        select(PurchaseDeliveryIncident).order_by(PurchaseDeliveryIncident.id)
    ).all()
    assert first.subject_id == recurring.subject_id == sale_id
    assert first.first_detected_at.replace(tzinfo=UTC) == NOW
    assert first.last_observed_at.replace(tzinfo=UTC) == second
    assert first.resolved_at.replace(tzinfo=UTC) == third
    assert recurring.first_detected_at.replace(tzinfo=UTC) == fourth
    assert recurring.resolved_at is None

    db_session.add(
        PurchaseDeliveryIncident(
            sale_id=sale_id,
            subject_id=sale_id,
            kind="email_failed",
            severity="error",
            first_detected_at=fourth,
            last_observed_at=fourth,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_persistence_failure_rolls_back_incidents(db_session):
    sale = db_session.get(Sale, create_purchase(db_session, "product"))
    sale.purchase_email_delivery = None
    db_session.commit()

    def fail_commit(session):
        session.flush()
        raise RuntimeError("monitoring persistence failed")

    event.listen(db_session, "before_commit", fail_commit, once=True)
    with pytest.raises(RuntimeError, match="monitoring persistence failed"):
        scan_purchase_delivery(db_session, now=NOW)
    assert db_session.scalar(select(PurchaseDeliveryIncident.id)) is None
    assert db_session.scalar(select(PurchaseEmailDelivery.id)) is None
    assert sale.payment_status == PaymentStatus.PAID


def test_refunded_sale_leaves_monitoring_scope(db_session):
    sale = db_session.get(Sale, create_purchase(db_session, "product"))
    sale.purchase_email_delivery.status = "failed"
    db_session.commit()
    assert scan_purchase_delivery(db_session, now=NOW)["opened"] == 1

    sale.payment_status = PaymentStatus.REFUNDED
    db_session.commit()
    summary = scan_purchase_delivery(db_session, now=NOW + timedelta(minutes=1))
    assert summary["paid_sales_scanned"] == 0
    assert summary["resolved"] == 1
    assert sale.purchase_email_delivery.status == "failed"
