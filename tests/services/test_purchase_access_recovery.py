from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models.download_entitlement import DownloadEntitlementStatus
from app.models.enums import PaymentStatus
from app.models.product_release import ProductRelease
from app.models.purchase_access_recovery import PurchaseAccessRecovery
from app.models.purchase_email_delivery import PurchaseEmailDeliveryStatus
from app.models.sale import Sale
from app.repositories.purchase_email_delivery_repository import read_due_email_recovery
from app.services.download_entitlement_service import (
    get_valid_download_entitlement_by_token,
    record_download_attempt,
)
from app.services.email_transport import (
    EmailTransportAmbiguousError,
    EmailTransportDefinitiveError,
    EmailTransportIdempotencyConflictError,
)
from app.services.payment_reconciliation_service import reconcile_payment_event
from app.services.purchase_access_recovery_service import (
    SEND_LEASE,
    VERIFY_CONFIRMATION,
    RecoveryConflictError,
    RecoveryInputError,
    prepare_purchase_access_recovery,
    send_purchase_access_recovery,
)
from app.services.purchase_email_delivery_service import (
    PurchaseEmailAttemptResult,
    attempt_purchase_email_delivery,
    authorize_reconciliation_resend,
    purchase_email_recovery_cutoffs,
)
from app.services.refund_service import start_full_refund
from tests.services.test_purchase_email_delivery_service import (
    RecordingTransport,
    configure_email,
    create_pending_sale,
    payment_event,
)


def create_paid_recovery_sale(db, *, kind="product", language="en"):
    sale = create_pending_sale(db, kind=kind, language=language)
    sale_id = sale.id
    reconcile_payment_event(db, payment_event(sale))
    db.commit()
    return sale_id


def prepare(db, sale_id, **overrides):
    values = {
        "sale_id": sale_id,
        "request_id": "a" * 32,
        "expected_recovery_id": 0,
        "verification": VERIFY_CONFIRMATION,
        "verification_method": "provider_dashboard",
        "reason": "Verified purchase and confirmed requested address.",
    }
    return prepare_purchase_access_recovery(db, **(values | overrides))


def send(db, sale_id, recovery_id, transport, *, attempt=0, now=None):
    return send_purchase_access_recovery(
        db,
        sale_id=sale_id,
        recovery_id=recovery_id,
        expected_attempt_count=attempt,
        transport=transport,
        clock=lambda: now or datetime.now(UTC),
    )


def prepared_sale(db, monkeypatch, *, language="en", corrected_email=""):
    configure_email(monkeypatch)
    sale_id = create_paid_recovery_sale(db, language=language)
    assert prepare(db, sale_id, corrected_email=corrected_email) == "prepared"
    recovery_id = db.query(PurchaseAccessRecovery.id).scalar()
    db.rollback()
    return sale_id, recovery_id


@pytest.mark.parametrize("new_email", ["", " Corrected@EXAMPLE.COM "])
def test_prepare_rotates_exact_release_and_preserves_history(
    db_session, monkeypatch, new_email
):
    db = db_session
    now = datetime.now(UTC)
    monkeypatch.setattr(settings, "DOWNLOAD_TOKEN_TTL_HOURS", 8)
    sale_id = create_paid_recovery_sale(db)
    sale = db.get(Sale, sale_id)
    grant = sale.items[0].download_entitlement
    purchase = (sale.external_payment_id, sale.amount, sale.currency, sale.paid_at)
    old_token, grant_id, release_id, reference = (
        grant.download_token,
        grant.id,
        grant.release_id,
        grant.support_reference,
    )
    grant.release.is_active = False
    db.flush()
    db.add(
        ProductRelease(
            product_id=grant.release.product_id,
            version="2.0",
            storage_provider="cloudflare_r2",
            storage_key="downloads/new.zip",
            original_filename="new.zip",
            is_active=True,
        )
    )
    grant.status = DownloadEntitlementStatus.EXPIRED
    grant.expires_at = now - timedelta(hours=1)
    grant.attempt_count = 3
    grant.first_attempt_at = now - timedelta(hours=5)
    grant.last_attempt_at = now - timedelta(hours=3)
    db.commit()

    assert (
        prepare(db, sale_id, corrected_email=new_email, clock=lambda: now) == "prepared"
    )
    assert (
        prepare(db, sale_id, corrected_email=new_email, clock=lambda: now)
        == "already_prepared"
    )
    with pytest.raises(RecoveryConflictError, match="stale"):
        prepare(db, sale_id, request_id="b" * 32)
    sale = db.get(Sale, sale_id)
    grant = sale.items[0].download_entitlement
    audit = db.query(PurchaseAccessRecovery).one()
    assert sale.customer_email == (
        "corrected@example.com" if new_email else "buyer@example.test"
    )
    assert audit.recipient == sale.customer_email
    assert audit.previous_email == ("buyer@example.test" if new_email else None)
    assert (
        sale.external_payment_id,
        sale.amount,
        sale.currency,
        sale.paid_at,
    ) == purchase
    assert sale.purchase_email_delivery.status == "pending"
    assert (grant.id, grant.release_id, grant.support_reference) == (
        grant_id,
        release_id,
        reference,
    )
    assert grant.expires_at.replace(tzinfo=UTC) == now + timedelta(hours=24)
    assert (grant.attempt_count, grant.first_attempt_at, grant.last_attempt_at) == (
        0,
        None,
        None,
    )
    assert audit.previous_status == "expired"
    assert audit.previous_attempt_count == 3
    assert audit.previous_first_attempt_at.replace(tzinfo=UTC) == now - timedelta(
        hours=5
    )
    assert audit.previous_last_attempt_at.replace(tzinfo=UTC) == now - timedelta(
        hours=3
    )
    assert audit.previous_expires_at.replace(tzinfo=UTC) == now - timedelta(hours=1)
    assert audit.verified_at.replace(tzinfo=UTC) == now
    assert audit.verification_method == "provider_dashboard"
    assert old_token != grant.download_token
    with pytest.raises(HTTPException) as exc:
        get_valid_download_entitlement_by_token(db, old_token)
    assert exc.value.status_code == 404
    assert record_download_attempt(db, grant.download_token).attempt_count == 1


@pytest.mark.parametrize(
    "scenario",
    [
        "unpaid",
        "refunded",
        "active_refund",
        "unresolved_refund",
        "consultation",
        "bundle",
        "wrong_release",
        "original_sending",
    ],
)
def test_ineligible_sales_cannot_prepare(db_session, scenario):
    db = db_session
    kind = scenario if scenario in {"consultation", "bundle"} else "product"
    sale_id = create_paid_recovery_sale(db, kind=kind)
    if scenario in {"active_refund", "unresolved_refund"}:
        operation = start_full_refund(db, sale_id=sale_id)
        if scenario == "unresolved_refund":
            operation.status = "reconciliation_required"
    sale = db.get(Sale, sale_id)
    if scenario in {"unpaid", "refunded"}:
        sale.payment_status = (
            PaymentStatus.PENDING if scenario == "unpaid" else PaymentStatus.REFUNDED
        )
    elif scenario == "wrong_release":
        db.add(
            ProductRelease(
                product_id=sale.product_id,
                version="2.0",
                storage_provider="cloudflare_r2",
                storage_key="downloads/new.zip",
                original_filename="new.zip",
                is_active=False,
            )
        )
        db.flush()
        sale.items[0].download_entitlement.release_id = (
            db.query(ProductRelease.id).filter_by(version="2.0").scalar()
        )
    elif scenario == "original_sending":
        sale.purchase_email_delivery.status = PurchaseEmailDeliveryStatus.SENDING
    db.commit()

    with pytest.raises(RecoveryConflictError):
        prepare(db, sale_id, corrected_email="corrected@example.com")
    assert db.query(PurchaseAccessRecovery).count() == 0
    assert db.get(Sale, sale_id).customer_email == "buyer@example.test"


@pytest.mark.parametrize(
    "overrides",
    [
        {"reason": " "},
        {"reason": "x" * 501},
        {"verification": ""},
        {"verification_method": "purchase_email"},
        {"corrected_email": "invalid"},
    ],
)
def test_prepare_requires_valid_operator_evidence(db_session, overrides):
    sale_id = create_paid_recovery_sale(db_session)
    with pytest.raises(RecoveryInputError):
        prepare(db_session, sale_id, **overrides)
    assert db_session.query(PurchaseAccessRecovery).count() == 0


def test_recovery_uses_current_grant_and_separate_identity_after_commit(
    db_session, monkeypatch
):
    db = db_session
    sale_id, recovery_id = prepared_sale(
        db, monkeypatch, language="ru", corrected_email="right@example.com"
    )
    grant = db.get(Sale, sale_id).items[0].download_entitlement
    token = grant.download_token
    db.rollback()

    def verify_outside_transaction():
        assert not db.in_transaction()

    delivery = RecordingTransport(on_send=verify_outside_transaction)
    assert send(db, sale_id, recovery_id, delivery) == "accepted"
    assert send(db, sale_id, recovery_id, delivery) == "accepted"
    (message,) = delivery.messages
    assert message.recipient == "right@example.com"
    assert "ваша покупка" in message.subject
    assert f"/download/{token}" in message.text_body
    assert "/consultation/" not in message.text_body
    assert message.idempotency_key == f"purchase-access-recovery/{recovery_id}"
    assert message.purchase_email_delivery_id is None
    assert message.purchase_access_recovery_id == recovery_id
    row = db.get(PurchaseAccessRecovery, recovery_id)
    assert row.provider_message_id == "resend-message-123"
    assert row.accepted_at is not None and len(row.payload_fingerprint) == 64
    assert db.get(Sale, sale_id).purchase_email_delivery.attempt_count == 0


def test_superseded_original_is_excluded_from_every_send_entry_point(
    db_session, monkeypatch
):
    db = db_session
    sale_id, _ = prepared_sale(db, monkeypatch)
    original = db.get(Sale, sale_id).purchase_email_delivery
    original.status = PurchaseEmailDeliveryStatus.RECONCILIATION_REQUIRED
    original.attempt_count = 3
    original_id = original.id
    db.commit()
    transport = RecordingTransport()
    assert (
        attempt_purchase_email_delivery(db, sale_id=sale_id, transport=transport)
        == PurchaseEmailAttemptResult.SUPERSEDED
    )
    assert (
        authorize_reconciliation_resend(
            db,
            sale_id=sale_id,
            transport=transport,
            provider_confirmed_not_sent=True,
        )
        == PurchaseEmailAttemptResult.SUPERSEDED
    )
    original = db.get(Sale, sale_id).purchase_email_delivery
    assert (original.id, original.status, original.attempt_count) == (
        original_id,
        PurchaseEmailDeliveryStatus.RECONCILIATION_REQUIRED,
        3,
    )
    original.status = PurchaseEmailDeliveryStatus.PENDING
    original.attempt_count = 0
    db.commit()
    due, candidates = read_due_email_recovery(
        db,
        purchase_email_recovery_cutoffs(
            datetime.now(UTC) + timedelta(minutes=20), allow_sends=True
        ),
        limit=20,
    )
    assert due == 0 and not candidates
    assert not transport.messages


@pytest.mark.parametrize(
    "failure,status",
    [
        (EmailTransportDefinitiveError, "failed"),
        (EmailTransportAmbiguousError, "ambiguous"),
    ],
)
def test_retry_uses_same_snapshot_and_ignores_replayed_send_form(
    db_session, monkeypatch, failure, status
):
    db = db_session
    sale_id, recovery_id = prepared_sale(db, monkeypatch)
    first = RecordingTransport(failure=failure("sensitive diagnostic"))
    assert send(db, sale_id, recovery_id, first) == status
    retry = RecordingTransport()
    assert send(db, sale_id, recovery_id, retry) == status
    assert not retry.messages
    assert send(db, sale_id, recovery_id, retry, attempt=1) == "accepted"
    assert first.messages == retry.messages
    row = db.get(PurchaseAccessRecovery, recovery_id)
    assert row.attempt_count == 2
    assert row.last_error is None


def test_interrupted_send_waits_for_lease_and_retries_same_key(db_session, monkeypatch):
    db = db_session
    sale_id, recovery_id = prepared_sale(db, monkeypatch)
    now = datetime.now(UTC)
    first = RecordingTransport(failure=RuntimeError("interrupted after claim"))
    with pytest.raises(RuntimeError, match="interrupted"):
        send(db, sale_id, recovery_id, first, now=now)
    retry = RecordingTransport()
    assert send(db, sale_id, recovery_id, retry, attempt=1, now=now) == "sending"
    assert not retry.messages
    assert (
        send(db, sale_id, recovery_id, retry, attempt=1, now=now + SEND_LEASE)
        == "accepted"
    )
    assert first.messages == retry.messages


@pytest.mark.parametrize(
    "unsafe", ["payload", "credentials", "elapsed", "provider_conflict"]
)
def test_unsafe_retry_requires_reconciliation_and_blocks_new_identity(
    db_session, monkeypatch, unsafe
):
    db = db_session
    sale_id, recovery_id = prepared_sale(db, monkeypatch)
    now = datetime.now(UTC)
    first = RecordingTransport(failure=EmailTransportAmbiguousError("timeout"))
    assert send(db, sale_id, recovery_id, first, now=now) == "ambiguous"
    transport = RecordingTransport(
        failure=(
            EmailTransportIdempotencyConflictError("changed")
            if unsafe == "provider_conflict"
            else None
        )
    )
    if unsafe == "payload":
        monkeypatch.setattr(settings, "MAIL_FROM_NAME", "Changed sender")
    if unsafe == "credentials":
        monkeypatch.setattr(settings, "RESEND_API_KEY", "changed-credential")
    if unsafe == "elapsed":
        now += timedelta(hours=23)
    assert (
        send(db, sale_id, recovery_id, transport, attempt=1, now=now)
        == "reconciliation_required"
    )
    assert len(transport.messages) == (1 if unsafe == "provider_conflict" else 0)
    with pytest.raises(RecoveryConflictError, match="Resolve the existing"):
        prepare(db, sale_id, request_id="b" * 32, expected_recovery_id=recovery_id)


def test_refund_and_newer_preparation_block_a_previously_prepared_send(
    db_session, monkeypatch
):
    db = db_session
    sale_id, old_recovery_id = prepared_sale(db, monkeypatch)
    assert (
        prepare(db, sale_id, request_id="b" * 32, expected_recovery_id=old_recovery_id)
        == "prepared"
    )
    current = (
        db.query(PurchaseAccessRecovery.id)
        .order_by(PurchaseAccessRecovery.id.desc())
        .first()[0]
    )
    db.rollback()
    transport = RecordingTransport()
    with pytest.raises(RecoveryConflictError, match="no longer current"):
        send(db, sale_id, old_recovery_id, transport)
    start_full_refund(db, sale_id=sale_id)
    with pytest.raises(RecoveryConflictError, match="without a refund"):
        send(db, sale_id, current, transport)
    assert not transport.messages
