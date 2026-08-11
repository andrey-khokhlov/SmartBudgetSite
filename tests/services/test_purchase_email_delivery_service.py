from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.config import settings
from app.models.consultation_entitlement import ConsultationEntitlement
from app.models.download_entitlement import DownloadEntitlement
from app.models.enums import PaymentStatus
from app.models.product import Product
from app.models.product_release import ProductRelease
from app.models.purchase_email_delivery import (
    PurchaseEmailDelivery,
    PurchaseEmailDeliveryStatus,
)
from app.models.sale import Sale
from app.models.service_addon import ServiceAddon
from app.schemas.webhooks import NormalizedPaymentEvent, PaymentOutcome
from app.services.email_transport import (
    EmailTransportAmbiguousError,
    EmailTransportDefinitiveError,
    EmailTransportResult,
    TransactionalEmail,
)
from app.services.payment_delivery_orchestration_service import (
    reconcile_payment_and_deliver,
)
from app.services.purchase_email_delivery_service import (
    PurchaseEmailAttemptResult,
    authorize_reconciliation_resend,
    deliver_purchase_email_after_payment_commit,
)
from app.services.sale_service import (
    create_product_sale,
    create_service_sale_item,
    create_standalone_service_sale,
)


class RecordingTransport:
    def __init__(self, *, failure: Exception | None = None, on_send=None) -> None:
        self.failure = failure
        self.on_send = on_send
        self.messages: list[TransactionalEmail] = []

    def send(self, email: TransactionalEmail) -> EmailTransportResult:
        if self.on_send is not None:
            self.on_send()
        self.messages.append(email)
        if self.failure is not None:
            raise self.failure
        return EmailTransportResult(provider_message_id="resend-message-123")


def configure_email(monkeypatch) -> None:
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://app.example.test")
    monkeypatch.setattr(settings, "MAIL_FROM_EMAIL", "support@example.test")
    monkeypatch.setattr(settings, "MAIL_FROM_NAME", "SmartBudget")


def create_pending_sale(db_session, *, kind: str) -> Sale:
    product = None
    release = None
    if kind in {"product", "bundle"}:
        product = Product(
            family_slug="smartbudget",
            slug=f"purchase-email-{kind}",
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
            storage_key=f"product-releases/purchase-email-{kind}/1.0.zip",
            original_filename="SmartBudget.zip",
            is_active=True,
        )
        db_session.add(release)
        db_session.flush()

    addon = None
    if kind in {"consultation", "bundle"}:
        addon = ServiceAddon(
            code=f"purchase_email_{kind}",
            name="Consultation",
            service_type="consultation",
            usage_type="standalone" if kind == "consultation" else "addon",
            family_slug="smartbudget",
            package_code="INT",
            currency_code="EUR",
            amount=Decimal("35.00"),
            is_active=True,
        )
        db_session.add(addon)
        db_session.flush()

    if kind == "consultation":
        sale = create_standalone_service_sale(
            db_session,
            service_addon_id=addon.id,
            service_name=addon.name,
            customer_email="buyer@example.test",
            amount=Decimal("35.00"),
            currency="EUR",
            payment_provider="lava_top",
            external_payment_id=f"purchase-email-{kind}",
        )
    else:
        sale = create_product_sale(
            db_session,
            product=product,
            product_release=release,
            customer_email="buyer@example.test",
            amount=Decimal("74.00" if kind == "bundle" else "39.00"),
            currency="EUR",
            payment_provider="lava_top",
            external_payment_id=f"purchase-email-{kind}",
        )
        if kind == "bundle":
            db_session.add(
                create_service_sale_item(
                    sale=sale,
                    service_addon_id=addon.id,
                    item_name=addon.name,
                    currency_code="EUR",
                    amount=addon.amount,
                )
            )
    db_session.commit()
    return sale


def payment_event(sale: Sale) -> NormalizedPaymentEvent:
    return NormalizedPaymentEvent(
        provider="lava_top",
        external_payment_id=sale.external_payment_id,
        outcome=PaymentOutcome.SUCCESS,
        amount=sale.amount,
        currency=sale.currency,
    )


def test_paid_fulfillment_commits_before_send_and_replay_is_safe(
    db_session, monkeypatch
):
    configure_email(monkeypatch)
    sale = create_pending_sale(db_session, kind="product")
    commit_count = 0
    real_commit = db_session.commit

    def tracked_commit():
        nonlocal commit_count
        commit_count += 1
        real_commit()

    def assert_committed_before_send():
        assert commit_count >= 2

    monkeypatch.setattr(db_session, "commit", tracked_commit)
    transport = RecordingTransport(on_send=assert_committed_before_send)

    reconcile_payment_and_deliver(
        db_session,
        payment_event(sale),
        transport=transport,
    )
    reconcile_payment_and_deliver(
        db_session,
        payment_event(sale),
        transport=transport,
    )

    db_session.expire_all()
    delivery = db_session.query(PurchaseEmailDelivery).one()
    assert commit_count >= 3
    assert len(transport.messages) == 1
    assert delivery.status == PurchaseEmailDeliveryStatus.SENT.value
    assert delivery.attempt_count == 1
    assert delivery.last_attempt_at is not None
    assert delivery.sent_at is not None
    assert delivery.provider_message_id == "resend-message-123"
    assert delivery.last_error is None
    assert transport.messages[0].idempotency_key == f"purchase-email/{delivery.id}"
    assert "/download/" in transport.messages[0].text_body


def test_definitive_failure_preserves_payment_and_retries_successfully(
    db_session, monkeypatch
):
    configure_email(monkeypatch)
    sale = create_pending_sale(db_session, kind="product")
    failed_transport = RecordingTransport(
        failure=EmailTransportDefinitiveError("private provider details")
    )

    reconcile_payment_and_deliver(
        db_session,
        payment_event(sale),
        transport=failed_transport,
    )
    db_session.expire_all()
    delivery = db_session.query(PurchaseEmailDelivery).one()
    assert db_session.get(Sale, sale.id).payment_status == PaymentStatus.PAID
    assert db_session.query(DownloadEntitlement).count() == 1
    assert delivery.status == PurchaseEmailDeliveryStatus.FAILED.value
    assert "private provider details" not in delivery.last_error

    successful_transport = RecordingTransport()
    result = deliver_purchase_email_after_payment_commit(
        db_session,
        sale_id=sale.id,
        transport=successful_transport,
    )
    db_session.refresh(delivery)
    assert result == PurchaseEmailAttemptResult.SENT
    assert delivery.status == PurchaseEmailDeliveryStatus.SENT.value
    assert delivery.attempt_count == 2


def test_ambiguous_retry_window_and_lazy_reconciliation(db_session, monkeypatch):
    configure_email(monkeypatch)
    sale = create_pending_sale(db_session, kind="product")
    initial_time = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)
    ambiguous = RecordingTransport(
        failure=EmailTransportAmbiguousError("secret download-token-value")
    )

    reconcile_payment_and_deliver(
        db_session,
        payment_event(sale),
        transport=ambiguous,
        now=initial_time,
    )
    delivery = db_session.query(PurchaseEmailDelivery).one()
    assert delivery.status == PurchaseEmailDeliveryStatus.SENDING.value

    retry = RecordingTransport()
    safe_result = deliver_purchase_email_after_payment_commit(
        db_session,
        sale_id=sale.id,
        transport=retry,
        now=initial_time + timedelta(hours=22),
    )
    assert safe_result == PurchaseEmailAttemptResult.SENT
    assert retry.messages[0].idempotency_key == f"purchase-email/{delivery.id}"

    delivery.status = PurchaseEmailDeliveryStatus.SENDING.value
    delivery.last_attempt_at = initial_time
    delivery.sending_started_at = initial_time
    delivery.sent_at = None
    delivery.provider_message_id = None
    db_session.commit()
    blocked_transport = RecordingTransport()
    old_result = deliver_purchase_email_after_payment_commit(
        db_session,
        sale_id=sale.id,
        transport=blocked_transport,
        now=initial_time + timedelta(hours=23),
    )
    db_session.refresh(delivery)
    assert old_result == PurchaseEmailAttemptResult.RECONCILIATION_REQUIRED
    assert delivery.status == PurchaseEmailDeliveryStatus.RECONCILIATION_REQUIRED.value
    assert blocked_transport.messages == []


def test_safe_retries_do_not_extend_original_ambiguous_window(db_session, monkeypatch):
    configure_email(monkeypatch)
    sale = create_pending_sale(db_session, kind="product")
    initial_time = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)
    ambiguous = RecordingTransport(failure=EmailTransportAmbiguousError("ambiguous"))
    reconcile_payment_and_deliver(
        db_session,
        payment_event(sale),
        transport=ambiguous,
        now=initial_time,
    )

    deliver_purchase_email_after_payment_commit(
        db_session,
        sale_id=sale.id,
        transport=ambiguous,
        now=initial_time + timedelta(hours=22),
    )
    delivery = db_session.query(PurchaseEmailDelivery).one()
    db_session.refresh(delivery)
    assert delivery.sending_started_at.replace(tzinfo=UTC) == initial_time
    assert delivery.last_attempt_at.replace(tzinfo=UTC) == initial_time + timedelta(
        hours=22
    )

    result = deliver_purchase_email_after_payment_commit(
        db_session,
        sale_id=sale.id,
        transport=RecordingTransport(),
        now=initial_time + timedelta(hours=23),
    )
    db_session.refresh(delivery)
    assert result == PurchaseEmailAttemptResult.RECONCILIATION_REQUIRED
    assert delivery.status == PurchaseEmailDeliveryStatus.RECONCILIATION_REQUIRED.value


def test_product_consultation_and_bundle_content(db_session, monkeypatch):
    configure_email(monkeypatch)
    for kind, expected_paths in [
        ("product", ["/download/"]),
        ("consultation", ["/consultation/book/"]),
        ("bundle", ["/download/", "/consultation/book/"]),
    ]:
        sale = create_pending_sale(db_session, kind=kind)
        transport = RecordingTransport()
        reconcile_payment_and_deliver(
            db_session,
            payment_event(sale),
            transport=transport,
        )
        assert len(transport.messages) == 1
        for path in expected_paths:
            assert path in transport.messages[0].text_body
        assert transport.messages[0].sender_email == "support@example.test"
        assert transport.messages[0].sender_name == "SmartBudget"

    assert db_session.query(DownloadEntitlement).count() == 2
    assert db_session.query(ConsultationEntitlement).count() == 2


def test_missing_configuration_fails_delivery_without_changing_payment(
    db_session, monkeypatch
):
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", None)
    monkeypatch.setattr(settings, "MAIL_FROM_EMAIL", "support@example.test")
    monkeypatch.setattr(settings, "MAIL_FROM_NAME", "SmartBudget")
    sale = create_pending_sale(db_session, kind="product")
    transport = RecordingTransport()

    reconcile_payment_and_deliver(
        db_session,
        payment_event(sale),
        transport=transport,
    )
    delivery = db_session.query(PurchaseEmailDelivery).one()
    assert db_session.get(Sale, sale.id).payment_status == PaymentStatus.PAID
    assert db_session.query(DownloadEntitlement).count() == 1
    assert delivery.status == PurchaseEmailDeliveryStatus.FAILED.value
    assert transport.messages == []


def test_sensitive_transport_error_is_not_persisted_or_logged(
    db_session, monkeypatch, caplog
):
    configure_email(monkeypatch)
    sale = create_pending_sale(db_session, kind="product")
    secret = "capability-token-never-record"
    transport = RecordingTransport(
        failure=EmailTransportAmbiguousError(f"provider exposed {secret}")
    )

    reconcile_payment_and_deliver(
        db_session,
        payment_event(sale),
        transport=transport,
    )
    delivery = db_session.query(PurchaseEmailDelivery).one()
    assert secret not in (delivery.last_error or "")
    assert secret not in caplog.text


def test_unexpected_transport_failure_cannot_change_committed_payment(
    db_session, monkeypatch
):
    configure_email(monkeypatch)
    sale = create_pending_sale(db_session, kind="product")
    transport = RecordingTransport(failure=ValueError("unexpected private detail"))

    result = reconcile_payment_and_deliver(
        db_session,
        payment_event(sale),
        transport=transport,
    )

    delivery = db_session.query(PurchaseEmailDelivery).one()
    assert result.sale_id == sale.id
    assert db_session.get(Sale, sale.id).payment_status == PaymentStatus.PAID
    assert db_session.query(DownloadEntitlement).count() == 1
    assert delivery.status == PurchaseEmailDeliveryStatus.SENDING.value


def test_reconciliation_resend_requires_explicit_operator_authorization(
    db_session, monkeypatch
):
    configure_email(monkeypatch)
    sale = create_pending_sale(db_session, kind="product")
    transport = RecordingTransport()
    reconcile_payment_and_deliver(
        db_session,
        payment_event(sale),
        transport=transport,
    )
    delivery = db_session.query(PurchaseEmailDelivery).one()
    delivery.status = PurchaseEmailDeliveryStatus.RECONCILIATION_REQUIRED.value
    delivery.sent_at = None
    delivery.provider_message_id = None
    db_session.commit()

    blocked = deliver_purchase_email_after_payment_commit(
        db_session,
        sale_id=sale.id,
        transport=RecordingTransport(),
    )
    assert blocked == PurchaseEmailAttemptResult.RECONCILIATION_REQUIRED

    authorized_transport = RecordingTransport()
    result = authorize_reconciliation_resend(
        db_session,
        sale_id=sale.id,
        provider_confirmed_not_sent=True,
        transport=authorized_transport,
    )
    assert result == PurchaseEmailAttemptResult.SENT
    assert len(authorized_transport.messages) == 1
