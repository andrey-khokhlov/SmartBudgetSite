from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import httpx
import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.calendly import calendly_api_client as api
from app.services.calendly import share_revocation_service as job
from tests.services.test_calendly_share_service import EVENT_TYPE, SHARE, share_resource
from tests.services.test_consultation_entitlement_service import (
    create_test_consultation_entitlement,
)
from tests.services.webhooks.test_reconciliation_service import verified_booking
from app.services.webhooks import reconciliation_service as reconciliation


@pytest.fixture
def due(db_session, monkeypatch):
    monkeypatch.setattr(
        job, "lock_recovery_pass", lambda *args, **kwargs: nullcontext(True)
    )
    now = datetime.now(UTC)
    entitlement = create_test_consultation_entitlement(db_session)
    entitlement.created_at = now - timedelta(days=14)
    entitlement.expires_at = now
    entitlement.provisioning_claimed_at = now - timedelta(days=1)
    entitlement.provisioning_reference = "A" * 22
    entitlement.calendly_event_type_uri = EVENT_TYPE
    entitlement.calendly_share_uri = SHARE
    db_session.flush()
    entitlement_id = entitlement.id
    db_session.commit()
    return entitlement, entitlement_id, now


@pytest.mark.parametrize(
    ("status", "offset", "selected"),
    [("available", 0, 1), ("expired", -10, 1), ("available", 1, 0), ("booked", -1, 0)],
)
def test_expiry_selection_and_confirmed_deletion(
    due, db_session, monkeypatch, status, offset, selected
):
    entitlement, _, now = due
    entitlement.expires_at = now + timedelta(seconds=offset)
    entitlement.status = status
    db_session.commit()
    delete = Mock()
    monkeypatch.setattr(job, "delete_share", delete)
    assert job.revoke_expired_shares(db_session, now=now)["selected"] == selected
    assert delete.call_count == selected
    db_session.refresh(entitlement)
    assert bool(entitlement.calendly_revoked_at) is bool(selected)
    assert entitlement.calendly_share_uri == SHARE
    assert entitlement.status == status
    db_session.commit()
    if selected:
        assert (
            job.revoke_expired_shares(db_session, now=now + timedelta(days=1))[
                "selected"
            ]
            == 0
        )
        delete.assert_called_once_with(SHARE)


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (204, None),
        (401, "unauthorized"),
        (403, "forbidden"),
        (404, "provider_not_found"),
        (409, "provider_conflict"),
        (429, "rate_limited"),
        (503, "temporary_error"),
    ],
)
def test_delete_response_classification(monkeypatch, status, outcome):
    monkeypatch.setattr(settings, "CALENDLY_PERSONAL_ACCESS_TOKEN", "test-pat")
    delete = Mock(
        return_value=httpx.Response(status, headers={"Retry-After": "180"}, content=b"")
    )
    monkeypatch.setattr(api.httpx, "delete", delete)
    if outcome:
        with pytest.raises(api.CalendlyAPIError) as failure:
            api.delete_share(SHARE)
        assert failure.value.outcome == outcome
        assert failure.value.retry_at > datetime.now(UTC) + timedelta(seconds=170)
    else:
        assert api.delete_share(SHARE) is None
    assert delete.call_args.args == (SHARE,)
    assert delete.call_args.kwargs["follow_redirects"] is False
    assert delete.call_args.kwargs["timeout"] == 5


def test_delete_timeout_is_ambiguous_and_rejects_foreign_hosts(monkeypatch):
    monkeypatch.setattr(settings, "CALENDLY_PERSONAL_ACCESS_TOKEN", "test-pat")
    delete = Mock(side_effect=httpx.ReadTimeout("private details"))
    monkeypatch.setattr(api.httpx, "delete", delete)
    with pytest.raises(ValueError):
        api.delete_share("https://example.test/shares/TEST")
    delete.assert_not_called()
    with pytest.raises(api.CalendlyAPIError) as failure:
        api.delete_share(SHARE)
    assert failure.value.outcome == "ambiguous_timeout"
    assert "private details" not in str(failure.value)


def test_provider_booked_preserves_delayed_timely_booking(due, db_session, monkeypatch):
    entitlement, entitlement_id, now = due
    delete = Mock(
        side_effect=api.CalendlyAPIError("conflict", outcome="provider_conflict")
    )
    monkeypatch.setattr(job, "delete_share", delete)
    monkeypatch.setattr(
        job, "recover_share", lambda *args: {"uri": SHARE, "status": "booked"}
    )
    assert job.revoke_expired_shares(db_session, now=now)["by_outcome"] == {
        "provider_booked": 1
    }
    db_session.refresh(entitlement)
    assert entitlement.calendly_revoked_at is None
    assert entitlement.status == "available"
    monkeypatch.setattr(settings, "SECRET_KEY", "test-secret")
    event, resources = verified_booking(entitlement, "TIMELY", now)
    monkeypatch.setattr(reconciliation, "get_resource", resources.__getitem__)
    assert (
        reconciliation.reconcile_booking_confirmed_event(db_session, event).id
        == entitlement_id
    )
    assert entitlement.status == "booked"
    db_session.commit()
    assert (
        job.revoke_expired_shares(db_session, now=now + timedelta(days=1))["selected"]
        == 0
    )
    delete.assert_called_once()


def test_claim_recovery_persists_identity_before_delete(due, db_session, monkeypatch):
    entitlement, entitlement_id, now = due
    entitlement.calendly_share_uri = None
    marker = f"SmartBudgetSite:{entitlement.provisioning_reference}"
    db_session.commit()
    lookup = Mock(
        side_effect=[
            api.CalendlyAPIError("absent or ambiguous", outcome="ownership_unresolved"),
            share_resource(marker),
        ]
    )
    monkeypatch.setattr(job, "recover_share", lookup)

    def delete(uri):
        assert uri == SHARE
        with Session(db_session.get_bind()) as fresh:
            assert (
                fresh.get(type(entitlement), entitlement_id).calendly_share_uri == SHARE
            )

    provider = Mock(side_effect=delete)
    monkeypatch.setattr(job, "delete_share", provider)
    assert job.revoke_expired_shares(db_session, now=now)[
        "unresolved_entitlements"
    ] == [entitlement_id]
    provider.assert_not_called()
    assert job.revoke_expired_shares(db_session, now=now + timedelta(minutes=2))[
        "by_outcome"
    ] == {"revoked": 1}
    assert lookup.call_args.args[:2] == (EVENT_TYPE, marker)


def test_crash_after_delete_does_not_infer_success_from_404(
    due, db_session, monkeypatch
):
    entitlement, entitlement_id, now = due
    cls = type(entitlement)
    bind = db_session.get_bind()
    real_lock = job._lock_entitlement

    def break_final_transaction(uri):
        monkeypatch.setattr(
            job, "_lock_entitlement", Mock(side_effect=RuntimeError("interrupted"))
        )

    delete = Mock(side_effect=break_final_transaction)
    monkeypatch.setattr(job, "delete_share", delete)
    with pytest.raises(RuntimeError):
        job.revoke_expired_shares(db_session, now=now)
    monkeypatch.setattr(job, "_lock_entitlement", real_lock)
    delete.side_effect = api.CalendlyAPIError("unknown", outcome="provider_not_found")
    with Session(bind) as restarted:
        assert job.revoke_expired_shares(restarted, now=now)["selected"] == 0
        result = job.revoke_expired_shares(restarted, now=now + timedelta(minutes=2))
        assert result["by_outcome"] == {"provider_not_found": 1}
        row = restarted.get(cls, entitlement_id)
        assert row.calendly_revoked_at is None
        assert row.calendly_revoke_attempts == 2
        assert row.calendly_revoke_next_at is not None


def test_rate_limit_and_dry_run_are_durable(due, db_session, monkeypatch):
    entitlement, _, now = due
    until = now + timedelta(minutes=45)
    delete = Mock(
        side_effect=api.CalendlyAPIError(
            "limit", outcome="rate_limited", retry_at=until
        )
    )
    monkeypatch.setattr(job, "delete_share", delete)
    assert job.revoke_expired_shares(db_session, dry_run=True, now=now)["selected"] == 1
    db_session.refresh(entitlement)
    assert not entitlement.calendly_revoke_attempts
    db_session.commit()
    delete.assert_not_called()
    assert job.revoke_expired_shares(db_session, now=now)["by_outcome"] == {
        "rate_limited": 1
    }
    assert job.revoke_expired_shares(db_session, now=now + timedelta(minutes=2)) == {
        "status": "rate_limited",
        "retry_at": until.isoformat(),
    }
    delete.assert_called_once()
