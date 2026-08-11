from decimal import Decimal

import pytest

from app.models.consultation_entitlement import ConsultationEntitlement
from app.models.download_entitlement import DownloadEntitlement
from app.models.enums import PaymentStatus
from app.models.product import Product
from app.models.product_release import ProductRelease
from app.models.purchase_email_delivery import PurchaseEmailDelivery
from app.models.sale import Sale
from app.models.service_addon import ServiceAddon
from app.schemas.webhooks import NormalizedPaymentEvent, PaymentOutcome
from app.services.payment_reconciliation_service import (
    PaymentFulfillmentError,
    PaymentReconciliationConflictError,
    PaymentReconciliationMismatchError,
    PaymentReconciliationResult,
    reconcile_payment_event,
)
from app.services.sale_service import create_product_sale, create_service_sale_item


def create_pending_sale(db_session, *, bundle: bool = False) -> Sale:
    product = Product(
        family_slug="smartbudget",
        slug=f"payment-reconciliation-{'bundle' if bundle else 'product'}",
        name="SmartBudget",
        edition="Standard",
        archive_path="archives/smartbudget.zip",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()
    release = ProductRelease(
        product_id=product.id,
        version="1.0",
        storage_provider="cloudflare_r2",
        storage_key=f"product-releases/{product.slug}/1.0.zip",
        original_filename="SmartBudget.zip",
        is_active=True,
    )
    db_session.add(release)
    db_session.flush()
    sale = create_product_sale(
        db_session,
        product=product,
        product_release=release,
        customer_email="buyer@example.com",
        amount=Decimal("85.00") if bundle else Decimal("50.00"),
        currency="RUB",
        payment_provider="lava_top",
        external_payment_id=f"invoice-{'bundle' if bundle else 'product'}",
    )
    if bundle:
        addon = ServiceAddon(
            code="consultation_payment_reconciliation",
            name="Consultation",
            service_type="consultation",
            usage_type="addon",
            family_slug="smartbudget",
            package_code="RU",
            currency_code="RUB",
            amount=Decimal("35.00"),
            is_active=True,
        )
        db_session.add(addon)
        db_session.flush()
        db_session.add(
            create_service_sale_item(
                sale=sale,
                service_addon_id=addon.id,
                item_name=addon.name,
                currency_code="RUB",
                amount=addon.amount,
            )
        )
    db_session.commit()
    return sale


def event(sale: Sale, outcome: PaymentOutcome) -> NormalizedPaymentEvent:
    return NormalizedPaymentEvent(
        provider="lava_top",
        external_payment_id=sale.external_payment_id,
        outcome=outcome,
        amount=sale.amount,
        currency=sale.currency,
    )


def test_success_fulfills_product_once_and_replay_is_idempotent(db_session):
    sale = create_pending_sale(db_session)

    first = reconcile_payment_event(db_session, event(sale, PaymentOutcome.SUCCESS))
    db_session.commit()
    second = reconcile_payment_event(db_session, event(sale, PaymentOutcome.SUCCESS))
    db_session.commit()

    db_session.refresh(sale)
    assert first.result == PaymentReconciliationResult.APPLIED
    assert second.result == PaymentReconciliationResult.IDEMPOTENT
    assert sale.payment_status == PaymentStatus.PAID
    assert db_session.query(DownloadEntitlement).count() == 1
    assert db_session.query(ConsultationEntitlement).count() == 0
    assert db_session.query(PurchaseEmailDelivery).count() == 1


def test_success_fulfills_product_and_consultation_bundle(db_session):
    sale = create_pending_sale(db_session, bundle=True)

    reconcile_payment_event(db_session, event(sale, PaymentOutcome.SUCCESS))
    db_session.commit()

    assert db_session.query(DownloadEntitlement).count() == 1
    assert db_session.query(ConsultationEntitlement).count() == 1
    assert db_session.query(PurchaseEmailDelivery).count() == 1
    product_item = next(item for item in sale.items if item.item_type == "product")
    service_item = next(item for item in sale.items if item.item_type == "service")
    assert product_item.consultation_entitlement is None
    assert service_item.download_entitlement is None


def test_failed_transition_and_duplicate_are_safe(db_session):
    sale = create_pending_sale(db_session)

    first = reconcile_payment_event(db_session, event(sale, PaymentOutcome.FAILED))
    second = reconcile_payment_event(db_session, event(sale, PaymentOutcome.FAILED))
    db_session.commit()

    assert first.result == PaymentReconciliationResult.APPLIED
    assert second.result == PaymentReconciliationResult.IDEMPOTENT
    assert sale.payment_status == PaymentStatus.FAILED
    assert db_session.query(DownloadEntitlement).count() == 0
    assert db_session.query(PurchaseEmailDelivery).count() == 0


@pytest.mark.parametrize(
    ("initial_status", "outcome"),
    [
        (PaymentStatus.PAID, PaymentOutcome.FAILED),
        (PaymentStatus.FAILED, PaymentOutcome.SUCCESS),
        (PaymentStatus.REFUNDED, PaymentOutcome.SUCCESS),
    ],
)
def test_terminal_conflict_never_rewrites_history(db_session, initial_status, outcome):
    sale = create_pending_sale(db_session)
    sale.payment_status = initial_status
    db_session.commit()

    with pytest.raises(PaymentReconciliationConflictError):
        reconcile_payment_event(db_session, event(sale, outcome))

    db_session.rollback()
    db_session.refresh(sale)
    assert sale.payment_status == initial_status


def test_unknown_invoice_and_snapshot_mismatch_are_controlled(db_session):
    sale = create_pending_sale(db_session)
    unknown = event(sale, PaymentOutcome.SUCCESS).model_copy(
        update={"external_payment_id": "unknown"}
    )
    wrong_amount = event(sale, PaymentOutcome.SUCCESS).model_copy(
        update={"amount": Decimal("51.00")}
    )

    with pytest.raises(PaymentReconciliationMismatchError):
        reconcile_payment_event(db_session, unknown)
    with pytest.raises(PaymentReconciliationMismatchError):
        reconcile_payment_event(db_session, wrong_amount)


def test_currency_mismatch_leaves_sale_pending_without_fulfillment(db_session):
    sale = create_pending_sale(db_session)
    wrong_currency = event(sale, PaymentOutcome.SUCCESS).model_copy(
        update={"currency": "EUR"}
    )

    with pytest.raises(PaymentReconciliationMismatchError):
        reconcile_payment_event(db_session, wrong_currency)

    db_session.expire_all()
    assert db_session.get(Sale, sale.id).payment_status == PaymentStatus.PENDING
    assert db_session.query(DownloadEntitlement).count() == 0
    assert db_session.query(ConsultationEntitlement).count() == 0


def test_bundle_fulfillment_failure_rolls_back_paid_and_product_entitlement(
    db_session,
):
    sale = create_pending_sale(db_session, bundle=True)
    service_item = next(item for item in sale.items if item.item_type == "service")
    service_item.service_addon.service_type = "support"
    db_session.commit()

    with pytest.raises(PaymentFulfillmentError):
        reconcile_payment_event(db_session, event(sale, PaymentOutcome.SUCCESS))
    db_session.rollback()

    db_session.refresh(sale)
    assert sale.payment_status == PaymentStatus.PENDING
    assert db_session.query(DownloadEntitlement).count() == 0
    assert db_session.query(ConsultationEntitlement).count() == 0
    assert db_session.query(PurchaseEmailDelivery).count() == 0


def test_product_fulfillment_failure_rolls_back_paid_transition(db_session):
    sale = create_pending_sale(db_session)
    product_item = sale.items[0]
    product_item.product_release_id = None
    db_session.commit()

    with pytest.raises(PaymentFulfillmentError):
        reconcile_payment_event(db_session, event(sale, PaymentOutcome.SUCCESS))
    db_session.rollback()

    db_session.refresh(sale)
    assert sale.payment_status == PaymentStatus.PENDING
    assert db_session.query(DownloadEntitlement).count() == 0
    assert db_session.query(PurchaseEmailDelivery).count() == 0


def test_paid_sale_without_complete_fulfillment_requires_attention(db_session):
    sale = create_pending_sale(db_session)
    sale.payment_status = PaymentStatus.PAID
    db_session.commit()

    with pytest.raises(PaymentFulfillmentError):
        reconcile_payment_event(db_session, event(sale, PaymentOutcome.SUCCESS))
