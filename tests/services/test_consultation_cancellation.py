from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models.enums import PaymentStatus
from app.services import consultation_cancellation_service as coordination
from app.services.calendly import share_revocation_service as revocation, share_service
from app.services.calendly.calendly_api_client import CalendlyAPIError
from app.services.consultation_entitlement_service import (
    get_valid_consultation_entitlement_by_token,
)
from app.services.refund_request_service import submit_refund_request
from app.services.refund_service import (
    ALTERNATIVE_DISPOSITION_EXCEPTION_REASONS,
    RefundConflictError,
    RefundVerificationRequiredError,
    confirm_full_refund,
    start_full_refund,
)
from app.services.webhooks import reconciliation_service as reconciliation
from tests.services.test_calendly_share_service import SHARE, share_resource
from tests.services.test_consultation_entitlement_service import (
    create_test_consultation_entitlement,
)
from tests.services.test_refund_service import VERIFIED_ALTERNATIVE
from tests.services.webhooks.test_reconciliation_service import (
    pin_share,
    verified_booking,
)

ROOT = "https://api.calendly.com"


@pytest.fixture
def consultation(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "test-key")
    entitlement = create_test_consultation_entitlement(db_session)
    pin_share(entitlement)
    entitlement.calendly_share_uri = None
    sale = entitlement.sale_item.sale
    sale.payment_provider = "lava_top"
    sale.external_payment_id = "test-consultation"
    db_session.commit()
    return entitlement


@pytest.mark.parametrize("alternative", [False, True])
def test_request_closes_access_and_revokes_unused_share_before_deadline(
    db_session, monkeypatch, consultation, alternative
):
    verification = (
        {"alternative_verification": VERIFIED_ALTERNATIVE}
        if alternative
        else {"provider_refund_verified": True}
    )
    sale = consultation.sale_item.sale
    sale_id, token = sale.id, consultation.booking_token
    consultation.calendly_share_uri = SHARE
    args = dict(
        email=sale.customer_email,
        reference=sale.sale_reference,
        message="",
        language="en",
        submission_token="a" * 64,
    )
    db_session.commit()
    assert submit_refund_request(db_session, **args) == "en"
    assert submit_refund_request(db_session, **args) == "en"
    assert consultation.cancellation.refund_request_id is not None
    assert consultation.status == "available"
    with pytest.raises(HTTPException) as denied:
        get_valid_consultation_entitlement_by_token(db_session, token)
    assert denied.value.status_code == 403
    db_session.rollback()
    monkeypatch.setattr(
        revocation, "lock_recovery_pass", lambda *args, **kwargs: nullcontext(True)
    )
    delete = Mock()
    monkeypatch.setattr(revocation, "delete_share", delete)
    start_full_refund(db_session, sale_id=sale_id)
    with pytest.raises(RefundConflictError):
        confirm_full_refund(db_session, sale_id=sale_id, **verification)
    assert revocation.revoke_expired_shares(db_session)["by_outcome"] == {"revoked": 1}
    delete.assert_called_once_with(SHARE)
    assert confirm_full_refund(db_session, sale_id=sale_id, **verification)


def test_inflight_share_is_retained_but_never_returned_after_access_closes(
    db_session, monkeypatch, consultation
):
    sale_id, token = consultation.sale_item.sale_id, consultation.booking_token
    monkeypatch.setattr(
        settings,
        "CALENDLY_CONSULTATION_EVENT_TYPE_URI",
        consultation.calendly_event_type_uri,
    )
    monkeypatch.setattr(settings, "CALENDLY_PERSONAL_ACCESS_TOKEN", "test-pat")
    db_session.commit()

    def create(event_type, marker):
        start_full_refund(db_session, sale_id=sale_id)
        return share_resource(marker)

    monkeypatch.setattr(share_service, "create_share", create)
    with pytest.raises(HTTPException) as denied:
        share_service.provision_booking_share(db_session, token)
    assert denied.value.status_code == 403
    assert consultation.calendly_share_uri == SHARE
    assert consultation.status == "available"


def booking(
    db_session, monkeypatch, entitlement, *, event_id="ORIGINAL", elapsed=False
):
    now = datetime.now(UTC)
    entitlement.calendly_share_uri = SHARE
    event, resources = verified_booking(entitlement, event_id, now)
    meeting = resources[f"/scheduled_events/{event_id}"]
    resources[f"/scheduled_events/{event_id}/invitees/INVITEE"].update(
        rescheduled=False, new_invitee=None,
    )
    meeting.update(
        start_time=(now + timedelta(hours=-2 if elapsed else 1)).isoformat(),
        end_time=(now + timedelta(hours=-1 if elapsed else 2)).isoformat(),
        invitees_counter={"active": 1},
    )
    resources["/event_types/TEST"] = {
        "uri": ROOT + "/event_types/TEST",
        "kind": "solo",
        "pooling_type": None,
    }
    monkeypatch.setattr(reconciliation, "get_resource", resources.__getitem__)
    monkeypatch.setattr(coordination, "get_resource", resources.__getitem__)
    db_session.flush()
    return event, resources


@pytest.mark.parametrize("elapsed", [False, True])
def test_direct_admin_refund_verifies_delayed_booking(
    db_session, monkeypatch, consultation, elapsed
):
    sale_id, entitlement_id = consultation.sale_item.sale_id, consultation.id
    event, resources = booking(db_session, monkeypatch, consultation, elapsed=elapsed)
    db_session.commit()
    start_full_refund(db_session, sale_id=sale_id)
    assert reconcile_delayed(db_session, event)
    assert consultation.status == "booked"
    db_session.commit()
    with pytest.raises(RefundConflictError):
        confirm_full_refund(db_session, sale_id=sale_id, provider_refund_verified=True)

    def cancel(*_args, **_kwargs):
        resources["/scheduled_events/ORIGINAL"]["status"] = "canceled"
        resources["/scheduled_events/ORIGINAL/invitees/INVITEE"]["status"] = "canceled"
        return {}

    provider = Mock(side_effect=cancel)
    monkeypatch.setattr(coordination, "api_request", provider)
    assert coordination.check_consultation_cancellation(
        db_session, sale_id, entitlement_id
    )
    assert consultation.cancellation.provider_outcome == (
        "elapsed" if elapsed else "cancelled"
    )
    assert consultation.cancellation.verified_at is not None
    assert provider.call_count == (0 if elapsed else 1)
    db_session.commit()
    result = confirm_full_refund(
        db_session, sale_id=sale_id, provider_refund_verified=True
    )
    assert result.operation.exceptional_confirmed_at is None
    assert consultation.status == "booked"


def reconcile_delayed(db_session, event):
    return (
        reconciliation.reconcile_booking_confirmed_event(db_session, event) is not None
    )


@pytest.mark.parametrize("alternative", [False, True])
def test_timeout_exception_requires_founder_reason_and_verified_money(
    db_session, monkeypatch, consultation, alternative
):
    verification = (
        {"alternative_verification": VERIFIED_ALTERNATIVE}
        if alternative
        else {"provider_refund_verified": True}
    )
    entered_reason = (
        "verification_unavailable"
        if alternative
        else "Provider timeout, refund cannot wait."
    )
    expected_reason = ALTERNATIVE_DISPOSITION_EXCEPTION_REASONS.get(
        entered_reason, entered_reason
    )
    sale_id, entitlement_id = consultation.sale_item.sale_id, consultation.id
    event, resources = booking(db_session, monkeypatch, consultation)
    assert reconcile_delayed(db_session, event)
    db_session.commit()
    start_full_refund(db_session, sale_id=sale_id)
    provider = Mock(
        side_effect=CalendlyAPIError("timeout", outcome="ambiguous_timeout")
    )
    monkeypatch.setattr(coordination, "api_request", provider)
    assert coordination.check_consultation_cancellation(
        db_session, sale_id, entitlement_id
    )
    assert not coordination.check_consultation_cancellation(
        db_session, sale_id, entitlement_id
    )
    provider.assert_called_once()
    assert consultation.cancellation.verified_at is None
    db_session.commit()
    with pytest.raises(RefundConflictError):
        confirm_full_refund(
            db_session,
            sale_id=sale_id,
            disposition_exception_acknowledged=True,
            **verification,
        )
    exception = dict(
        disposition_exception_acknowledged=True,
        disposition_exception_reason=entered_reason,
    )
    with pytest.raises(RefundVerificationRequiredError):
        confirm_full_refund(db_session, sale_id=sale_id, **exception)
    result = confirm_full_refund(
        db_session, sale_id=sale_id, **verification, **exception
    )
    assert result.operation.exceptional_confirmed_at
    assert result.operation.exceptional_confirmation_reason == expected_reason
    assert consultation.sale_item.sale.payment_status == PaymentStatus.REFUNDED


def test_verified_old_meeting_does_not_authorize_refund_after_reschedule(
    db_session, monkeypatch, consultation
):
    sale_id, entitlement_id = consultation.sale_item.sale_id, consultation.id
    original, resources = booking(db_session, monkeypatch, consultation, elapsed=True)
    assert reconcile_delayed(db_session, original)
    db_session.commit()
    start_full_refund(db_session, sale_id=sale_id)
    assert coordination.check_consultation_cancellation(
        db_session, sale_id, entitlement_id
    )
    replacement, extra = verified_booking(
        consultation,
        "NEW",
        datetime.now(UTC),
        old_invitee=original.provider_invitee_uri,
    )
    resources.update(extra)
    assert reconcile_delayed(db_session, replacement)
    assert consultation.cancellation.event_uri == replacement.provider_event_uri
    assert consultation.cancellation.verified_at is None
    db_session.commit()
    with pytest.raises(RefundConflictError):
        confirm_full_refund(db_session, sale_id=sale_id, provider_refund_verified=True)


def test_confirmation_rechecks_provider_for_replacement_without_webhook(
    db_session, monkeypatch, consultation
):
    sale_id, entitlement_id = consultation.sale_item.sale_id, consultation.id
    original, resources = booking(db_session, monkeypatch, consultation, elapsed=True)
    assert reconcile_delayed(db_session, original)
    db_session.commit()
    start_full_refund(db_session, sale_id=sale_id)
    assert coordination.check_consultation_cancellation(
        db_session, sale_id, entitlement_id
    )

    replacement, replacement_resources = verified_booking(
        consultation,
        "NEW",
        datetime.now(UTC),
        old_invitee=original.provider_invitee_uri,
    )
    resources.update(
        {path: row for path, row in replacement_resources.items() if "/NEW" in path}
    )
    resources["/scheduled_events/ORIGINAL"]["status"] = "canceled"
    resources["/scheduled_events/ORIGINAL/invitees/INVITEE"].update(
        status="canceled",
        rescheduled=True,
        new_invitee=replacement.provider_invitee_uri,
    )
    now = datetime.now(UTC)
    resources["/scheduled_events/NEW"].update(
        start_time=(now + timedelta(hours=1)).isoformat(),
        end_time=(now + timedelta(hours=2)).isoformat(),
        invitees_counter={"active": 1},
    )
    resources["/scheduled_events/NEW/invitees/INVITEE"].update(
        rescheduled=False, new_invitee=None,
    )
    provider = Mock()
    monkeypatch.setattr(coordination, "api_request", provider)
    db_session.commit()
    with pytest.raises(RefundConflictError):
        confirm_full_refund(db_session, sale_id=sale_id, provider_refund_verified=True)
    provider.assert_not_called()
    assert consultation.cancellation.event_uri == replacement.provider_event_uri
    assert consultation.cancellation.verified_at is None
    assert consultation.provider_event_uri == original.provider_event_uri


def test_exception_preserves_delayed_booking_evidence_after_refund(
    db_session, monkeypatch, consultation
):
    sale_id = consultation.sale_item.sale_id
    event, _ = booking(db_session, monkeypatch, consultation)
    consultation.calendly_revoke_outcome = "provider_booked"
    db_session.commit()
    start_full_refund(db_session, sale_id=sale_id)
    confirm_full_refund(
        db_session,
        sale_id=sale_id,
        provider_refund_verified=True,
        disposition_exception_acknowledged=True,
        disposition_exception_reason="Provider booked Share without a known invitee.",
    )
    assert consultation.status == "cancelled"
    assert reconcile_delayed(db_session, event)
    assert consultation.cancellation.event_uri == event.provider_event_uri
    assert consultation.cancellation.verified_at is None
    assert consultation.status == "cancelled"


def test_retry_after_uncertain_post_rechecks_before_sending(
    db_session, monkeypatch, consultation
):
    sale_id, entitlement_id = consultation.sale_item.sale_id, consultation.id
    event, resources = booking(db_session, monkeypatch, consultation)
    assert reconcile_delayed(db_session, event)
    db_session.commit()
    start_full_refund(db_session, sale_id=sale_id)
    provider = Mock(
        side_effect=CalendlyAPIError("timeout", outcome="ambiguous_timeout")
    )
    monkeypatch.setattr(coordination, "api_request", provider)
    assert coordination.check_consultation_cancellation(
        db_session, sale_id, entitlement_id
    )
    resources["/scheduled_events/ORIGINAL"]["status"] = "canceled"
    resources["/scheduled_events/ORIGINAL/invitees/INVITEE"]["status"] = "canceled"
    consultation.cancellation.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    assert coordination.check_consultation_cancellation(
        db_session, sale_id, entitlement_id
    )
    provider.assert_called_once()
    assert consultation.cancellation.provider_outcome == "cancelled"
    assert consultation.cancellation.verified_at


def test_consultation_request_does_not_change_separate_product_sale(
    db_session, consultation
):
    from tests.services.test_refund_service import create_sale

    sale = consultation.sale_item.sale
    args = dict(
        email=sale.customer_email,
        reference=sale.sale_reference,
        message="",
        language="en",
        submission_token="b" * 64,
    )
    db_session.commit()
    product_sale, download, _ = create_sale(db_session)
    product_sale.customer_email = args["email"]
    db_session.commit()
    assert submit_refund_request(db_session, **args) == "en"
    assert product_sale.payment_status == PaymentStatus.PAID
    assert download.status == "available"


def test_already_cancelled_delayed_booking_still_has_disposition_evidence(
    db_session, monkeypatch, consultation,
):
    sale_id, entitlement_id = consultation.sale_item.sale_id, consultation.id
    event, resources = booking(db_session, monkeypatch, consultation)
    resources["/scheduled_events/ORIGINAL"]["status"] = "canceled"
    resources["/scheduled_events/ORIGINAL/invitees/INVITEE"]["status"] = "canceled"
    db_session.commit()
    start_full_refund(db_session, sale_id=sale_id)
    assert reconcile_delayed(db_session, event)
    assert consultation.cancellation.event_uri == event.provider_event_uri
    assert consultation.status == "available"
    db_session.commit()
    assert not revocation.Repository.due_share_revocations(db_session, datetime.now(UTC), 20)
    db_session.commit()
    provider = Mock()
    monkeypatch.setattr(coordination, "api_request", provider)
    assert coordination.check_consultation_cancellation(db_session, sale_id, entitlement_id)
    provider.assert_not_called()
    assert consultation.cancellation.provider_outcome == "cancelled"
