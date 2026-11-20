from datetime import UTC, datetime
from decimal import Decimal
from inspect import signature

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models.consultation_entitlement import (
    ConsultationEntitlement,
)
from app.models.download_entitlement import (
    DownloadEntitlement,
    DownloadEntitlementStatus,
)
from app.models.enums import PaymentStatus
from app.models.product import Product
from app.models.product_release import ProductRelease
from app.models.refund_operation import (
    RefundConfirmationMethod,
    RefundOperation,
    RefundOperationStatus,
)
from app.models.refund_request import RefundRequest
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.service_addon import ServiceAddon
from app.services.refund_service import (
    AlternativeRefundVerification,
    RefundActionResult,
    RefundConflictError,
    RefundEligibilityError,
    RefundPersistenceError,
    RefundVerificationRequiredError,
    confirm_full_refund,
    start_full_refund,
)
from tests.services.test_consultation_entitlement_service import (
    create_test_consultation_entitlement,
)

VERIFIED_ALTERNATIVE = AlternativeRefundVerification(
    customer_agreed=True,
    transfer_verified=True,
    evidence_retained=True,
    original_refund_not_executed=True,
)


def create_sale(
    db_session,
    *,
    payment_status=PaymentStatus.PAID,
    payment_provider="lava_top",
    external_payment_id="refund-invoice",
    product_status=DownloadEntitlementStatus.AVAILABLE.value,
    consultation_status=None,
):
    db_session.expire_on_commit = False
    product = Product(
        family_slug="smartbudget",
        slug=f"refund-product-{external_payment_id or 'missing'}",
        name="SmartBudget",
        edition="Standard",
        archive_path="archives/refund.zip",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()
    release = ProductRelease(
        product_id=product.id,
        version="1.0",
        storage_provider="cloudflare_r2",
        storage_key=f"product-releases/refund/{product.id}.zip",
        original_filename="SmartBudget.zip",
        is_active=True,
    )
    db_session.add(release)
    db_session.flush()
    sale = Sale(
        customer_email="refund-buyer@example.com",
        amount=(
            Decimal("85.00") if consultation_status is not None else Decimal("50.00")
        ),
        currency="RUB",
        payment_provider=payment_provider,
        payment_status=payment_status,
        external_payment_id=external_payment_id,
    )
    product_item = SaleItem(
        sale=sale,
        item_type="product",
        product_id=product.id,
        product_release_id=release.id,
        item_name="SmartBudget",
        currency_code="RUB",
        amount=Decimal("50.00"),
        quantity=1,
    )
    db_session.add_all([sale, product_item])
    db_session.flush()
    download = DownloadEntitlement(
        sale_item_id=product_item.id,
        release_id=release.id,
        download_token=f"download-{sale.id}",
        support_reference=f"RF{sale.id:09d}",
        status=product_status,
        expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        attempt_count=0,
    )
    db_session.add(download)

    consultation = None
    if consultation_status is not None:
        addon = ServiceAddon(
            code=f"refund-consultation-{sale.id}",
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
        service_item = SaleItem(
            sale=sale,
            item_type="service",
            service_addon_id=addon.id,
            item_name="Consultation",
            currency_code="RUB",
            amount=Decimal("35.00"),
            quantity=1,
        )
        db_session.add(service_item)
        db_session.flush()
        consultation = ConsultationEntitlement(
            sale_item_id=service_item.id,
            booking_token=f"booking-{sale.id}",
            status=consultation_status,
            expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        )
        db_session.add(consultation)
    db_session.commit()
    return sale, download, consultation


def test_paid_sale_creates_one_pending_full_refund_snapshot(db_session):
    sale, _, _ = create_sale(db_session)

    operation = start_full_refund(db_session, sale_id=sale.id)

    assert operation.status == RefundOperationStatus.PENDING.value
    assert operation.amount == sale.amount
    assert operation.currency == sale.currency
    assert operation.payment_provider == sale.payment_provider
    assert operation.external_payment_id == sale.external_payment_id
    assert operation.provider_refund_id is None
    assert operation.provider_status is None
    assert db_session.query(RefundOperation).count() == 1


def test_refund_workflow_exposes_no_partial_amount_input():
    assert "amount" not in signature(start_full_refund).parameters


@pytest.mark.parametrize(
    "payment_status",
    [PaymentStatus.PENDING, PaymentStatus.FAILED, PaymentStatus.REFUNDED],
)
def test_non_paid_sale_cannot_start_refund(db_session, payment_status):
    sale, _, _ = create_sale(db_session, payment_status=payment_status)

    with pytest.raises(RefundEligibilityError):
        start_full_refund(db_session, sale_id=sale.id)

    assert db_session.query(RefundOperation).count() == 0


@pytest.mark.parametrize(
    ("payment_provider", "external_payment_id"),
    [(None, "invoice"), ("", "invoice"), ("lava_top", None), ("lava_top", "")],
)
def test_missing_provider_identity_is_rejected(
    db_session, payment_provider, external_payment_id
):
    sale, _, _ = create_sale(
        db_session,
        payment_provider=payment_provider,
        external_payment_id=external_payment_id,
    )

    with pytest.raises(RefundEligibilityError):
        start_full_refund(db_session, sale_id=sale.id)


def test_repeated_start_returns_same_operation_and_unique_constraint_blocks_second(
    db_session,
):
    sale, _, _ = create_sale(db_session)
    first = start_full_refund(db_session, sale_id=sale.id)
    second = start_full_refund(db_session, sale_id=sale.id)

    assert second.id == first.id
    assert db_session.query(RefundOperation).count() == 1

    db_session.add(
        RefundOperation(
            sale_id=sale.id,
            status=RefundOperationStatus.PENDING.value,
            amount=sale.amount,
            currency=sale.currency,
            payment_provider=sale.payment_provider,
            external_payment_id=sale.external_payment_id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@pytest.mark.parametrize(
    "operation_status",
    [
        RefundOperationStatus.CONFIRMED.value,
        RefundOperationStatus.RECONCILIATION_REQUIRED.value,
    ],
)
def test_existing_terminal_or_uncertain_operation_prevents_second_refund(
    db_session, operation_status
):
    sale, _, _ = create_sale(db_session)
    first = start_full_refund(db_session, sale_id=sale.id)
    first.status = operation_status
    db_session.commit()

    repeated = start_full_refund(db_session, sale_id=sale.id)

    assert repeated.id == first.id
    assert db_session.query(RefundOperation).count() == 1


def test_confirmation_refunds_sale_and_is_idempotent(db_session):
    sale, download, _ = create_sale(db_session)
    sale.sale_reference = "PAY-AAAAAAAAAAAAAA"
    request = RefundRequest(
        submission_token="a" * 64,
        sale_id=sale.id,
        purchase_reference=sale.sale_reference,
        customer_email=sale.customer_email,
        submitted_at=datetime.now(UTC),
        language="en",
        composition="product",
        status="pending",
    )
    db_session.add(request)
    db_session.commit()
    operation = start_full_refund(db_session, sale_id=sale.id)

    first = confirm_full_refund(
        db_session, sale_id=sale.id, provider_refund_verified=True
    )
    second = confirm_full_refund(
        db_session, sale_id=sale.id, provider_refund_verified=True
    )
    with pytest.raises(RefundConflictError, match="cannot change"):
        confirm_full_refund(
            db_session, sale_id=sale.id, alternative_verification=VERIFIED_ALTERNATIVE
        )

    db_session.refresh(sale)
    db_session.refresh(operation)
    db_session.refresh(download)
    assert first.result == RefundActionResult.APPLIED
    assert second.result == RefundActionResult.IDEMPOTENT
    assert sale.payment_status == PaymentStatus.REFUNDED
    assert operation.status == RefundOperationStatus.CONFIRMED.value
    assert operation.confirmation_method == RefundConfirmationMethod.ORIGINAL_PROVIDER
    assert operation.confirmed_at is not None
    assert download.status == DownloadEntitlementStatus.CANCELLED.value
    db_session.refresh(request)
    assert request.status == "pending"
    assert request.first_responded_at is None and request.closed_at is None


def test_confirmation_requires_explicit_provider_verification(db_session):
    sale, _, _ = create_sale(db_session)
    start_full_refund(db_session, sale_id=sale.id)

    with pytest.raises(RefundVerificationRequiredError):
        confirm_full_refund(db_session, sale_id=sale.id)

    assert sale.payment_status == PaymentStatus.PAID


def test_confirmation_rejects_mixed_verification_methods(db_session):
    sale, _, _ = create_sale(db_session)
    operation = start_full_refund(db_session, sale_id=sale.id)
    with pytest.raises(RefundVerificationRequiredError):
        confirm_full_refund(
            db_session,
            sale_id=sale.id,
            provider_refund_verified=True,
            alternative_verification=VERIFIED_ALTERNATIVE,
        )
    assert operation.confirmation_method is None
    assert sale.payment_status == PaymentStatus.PAID


@pytest.mark.parametrize("refunded_purchase", ["product", "consultation"])
def test_alternative_confirmation_reconciles_only_the_selected_sale(
    db_session, refunded_purchase
):
    product, download, _ = create_sale(db_session)
    consultation = create_test_consultation_entitlement(db_session)
    standalone = consultation.sale_item.sale
    standalone.payment_provider = "lava_top"
    standalone.external_payment_id = "standalone-refund-invoice"
    db_session.commit()
    sale, independent = (
        (product, standalone)
        if refunded_purchase == "product"
        else (standalone, product)
    )
    sale_id, independent_id = sale.id, independent.id
    operation = start_full_refund(db_session, sale_id=sale_id)
    operation.provider_status = "provider_unavailable"
    operation.provider_observed_at = datetime.now(UTC)
    db_session.commit()
    snapshot = (
        operation.id,
        operation.amount,
        operation.currency,
        operation.payment_provider,
        operation.external_payment_id,
        operation.provider_status,
        operation.provider_observed_at,
    )

    first = confirm_full_refund(
        db_session, sale_id=sale_id, alternative_verification=VERIFIED_ALTERNATIVE
    )
    confirmed_at = first.operation.confirmed_at
    replay = confirm_full_refund(
        db_session, sale_id=sale_id, alternative_verification=VERIFIED_ALTERNATIVE
    )
    with pytest.raises(RefundConflictError, match="cannot change"):
        confirm_full_refund(db_session, sale_id=sale_id, provider_refund_verified=True)

    db_session.refresh(operation)
    db_session.refresh(download)
    db_session.refresh(consultation)
    assert first.result == RefundActionResult.APPLIED
    assert replay.result == RefundActionResult.IDEMPOTENT
    assert (
        operation.confirmation_method == RefundConfirmationMethod.ALTERNATIVE_TRANSFER
    )
    assert confirmed_at is not None
    assert operation.confirmed_at.replace(tzinfo=UTC) == confirmed_at
    assert (
        operation.id,
        operation.amount,
        operation.currency,
        operation.payment_provider,
        operation.external_payment_id,
        operation.provider_status,
        operation.provider_observed_at.replace(tzinfo=UTC),
    ) == snapshot
    assert db_session.get(Sale, sale_id).payment_status == PaymentStatus.REFUNDED
    assert db_session.get(Sale, independent_id).payment_status == PaymentStatus.PAID
    assert download.status == (
        "cancelled" if refunded_purchase == "product" else "available"
    )
    assert consultation.status == (
        "cancelled" if refunded_purchase == "consultation" else "available"
    )
    assert db_session.query(RefundOperation).count() == 1


def test_snapshot_mismatch_and_conflicting_sale_state_fail_closed(db_session):
    sale, download, _ = create_sale(db_session)
    operation = start_full_refund(db_session, sale_id=sale.id)
    operation.amount = Decimal("49.00")
    db_session.commit()

    with pytest.raises(RefundConflictError):
        confirm_full_refund(
            db_session, sale_id=sale.id, provider_refund_verified=True
        )
    db_session.expire_all()
    assert db_session.get(Sale, sale.id).payment_status == PaymentStatus.PAID
    assert db_session.get(RefundOperation, operation.id).status == "pending"
    assert db_session.get(DownloadEntitlement, download.id).status == "available"

    operation.amount = sale.amount
    sale.payment_status = PaymentStatus.FAILED
    db_session.commit()
    with pytest.raises(RefundConflictError):
        confirm_full_refund(
            db_session, sale_id=sale.id, provider_refund_verified=True
        )


@pytest.mark.parametrize(
    ("initial", "expected"),
    [
        ("available", "cancelled"),
        ("completed", "completed"),
        ("expired", "expired"),
        ("cancelled", "cancelled"),
    ],
)
def test_download_entitlement_history_rules(db_session, initial, expected):
    sale, download, _ = create_sale(db_session, product_status=initial)
    start_full_refund(db_session, sale_id=sale.id)
    confirm_full_refund(db_session, sale_id=sale.id, provider_refund_verified=True)
    db_session.refresh(download)
    assert download.status == expected


@pytest.mark.parametrize(
    ("initial", "expected"),
    [
        ("available", "cancelled"),
        ("booked", "booked"),
        ("expired", "expired"),
        ("cancelled", "cancelled"),
    ],
)
def test_consultation_entitlement_history_rules(db_session, initial, expected):
    sale, download, consultation = create_sale(db_session, consultation_status=initial)
    sale_id, entitlement_id = sale.id, consultation.id
    start_full_refund(db_session, sale_id=sale.id)
    if initial == "booked":
        # This historical booking has no provider identity to verify.
        with pytest.raises(RefundConflictError):
            confirm_full_refund(db_session, sale_id=sale.id, provider_refund_verified=True)
        from app.services.consultation_cancellation_service import check_consultation_cancellation
        db_session.rollback()
        assert check_consultation_cancellation(db_session, sale_id, entitlement_id)
        confirm_full_refund(
            db_session, sale_id=sale_id, provider_refund_verified=True,
            disposition_exception_acknowledged=True,
            disposition_exception_reason="Historical booking identity unavailable.",
        )
    else:
        confirm_full_refund(db_session, sale_id=sale.id, provider_refund_verified=True)
    db_session.refresh(download)
    db_session.refresh(consultation)
    assert download.status == "cancelled"
    assert consultation.status == expected


def test_bundle_reconciliation_failure_rolls_back_everything(db_session, monkeypatch):
    sale, download, consultation = create_sale(
        db_session, consultation_status="available"
    )
    operation = start_full_refund(db_session, sale_id=sale.id)

    def fail_flush(*args, **kwargs):
        raise SQLAlchemyError("forced reconciliation failure")

    monkeypatch.setattr(db_session, "flush", fail_flush)
    with pytest.raises(RefundPersistenceError):
        confirm_full_refund(
            db_session, sale_id=sale.id, provider_refund_verified=True
        )

    db_session.expire_all()
    assert db_session.get(Sale, sale.id).payment_status == PaymentStatus.PAID
    assert db_session.get(RefundOperation, operation.id).status == "pending"
    assert db_session.get(DownloadEntitlement, download.id).status == "available"
    assert (
        db_session.get(ConsultationEntitlement, consultation.id).status == "available"
    )
