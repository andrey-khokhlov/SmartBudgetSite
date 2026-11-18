import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC
from threading import Barrier, Event
from unittest.mock import Mock

import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.consultation_entitlement import ConsultationEntitlement
from app.services.calendly import share_revocation_service as revocation
from app.services.calendly import share_service as shares
from app.services.webhooks import reconciliation_service as reconciliation
from tests.services.test_calendly_share_service import EVENT_TYPE, SHARE, share_resource
from tests.services.test_consultation_entitlement_service import (
    create_test_consultation_entitlement,
)
from tests.services.webhooks.test_reconciliation_service import verified_booking
from tests.test_purchase_email_failure_classification_postgres import (
    disposable_postgres,  # noqa: F401
)

PREVIOUS = "24d760e4bc31"
REVISION = "6f3c1a8d905e"


def test_share_migration_and_concurrent_claims(disposable_postgres, monkeypatch):  # noqa: F811
    engine, env = disposable_postgres

    def alembic(*args, succeeds=True):
        result = subprocess.run(
            [sys.executable, "-B", "-m", "alembic", *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert (result.returncode == 0) == succeeds, result.stderr
        return result

    alembic("upgrade", "head")
    alembic("check")
    with Session(engine) as db:
        entitlement = create_test_consultation_entitlement(db)
        entitlement_id, token = entitlement.id, entitlement.booking_token
        db.commit()
    alembic("downgrade", PREVIOUS)
    assert "calendly_share_uri" not in {
        item["name"]
        for item in inspect(engine).get_columns("consultation_entitlements")
    }
    alembic("upgrade", "head")
    uniques = {
        tuple(item["column_names"])
        for item in inspect(engine).get_unique_constraints("consultation_entitlements")
    }
    assert {("provisioning_reference",), ("calendly_share_uri",)} <= uniques
    with Session(engine) as db:
        entitlement = db.get(ConsultationEntitlement, entitlement_id)
        assert entitlement.booking_token == token
        assert entitlement.provisioning_reference is None

    monkeypatch.setattr(settings, "SECRET_KEY", "postgres-test-secret")
    monkeypatch.setattr(settings, "CALENDLY_CONSULTATION_EVENT_TYPE_URI", EVENT_TYPE)
    monkeypatch.setattr(settings, "CALENDLY_PERSONAL_ACCESS_TOKEN", "test-pat")
    post_started, release_post = Event(), Event()

    def create_share(event_type, marker):
        post_started.set()
        assert release_post.wait(10)
        return share_resource(marker)

    create = Mock(side_effect=create_share)
    monkeypatch.setattr(shares, "create_share", create)
    monkeypatch.setattr(
        shares,
        "find_share",
        Mock(side_effect=shares.CalendlyAPIError("not visible yet")),
    )

    def provision():
        with Session(engine) as db:
            return shares.provision_booking_share(db, token)

    with ThreadPoolExecutor(max_workers=2) as jobs:
        first = jobs.submit(provision)
        try:
            assert post_started.wait(10)
            with pytest.raises(shares.CalendlyAPIError):
                jobs.submit(provision).result(10)
        finally:
            release_post.set()
        assert first.result(10).startswith("https://calendly.com/d/")
    create.assert_called_once()
    assert (
        "Share ownership would be lost"
        in alembic("downgrade", PREVIOUS, succeeds=False).stderr
    )

    with Session(engine) as db:
        entitlement = db.get(ConsultationEntitlement, entitlement_id)
        booked_at = entitlement.expires_at.astimezone(UTC)
        one, resources = verified_booking(entitlement, "ONE", booked_at)
        two, other = verified_booking(entitlement, "TWO", booked_at)
        resources.update(other)
    barrier = Barrier(2)

    def fetch(path):
        if "/invitees/" in path:
            barrier.wait(10)
        return resources[path]

    monkeypatch.setattr(reconciliation, "get_resource", fetch)

    def reconcile(event):
        with Session(engine) as db, db.begin():
            return (
                reconciliation.reconcile_booking_confirmed_event(db, event) is not None
            )

    with ThreadPoolExecutor(max_workers=2) as jobs:
        attempts = [jobs.submit(reconcile, event) for event in (one, two)]
        assert sorted(job.result(15) for job in attempts) == [False, True]
    with Session(engine) as db:
        entitlement = db.get(ConsultationEntitlement, entitlement_id)
        assert entitlement.status == "booked"
        assert entitlement.provider_event_uri in {
            one.provider_event_uri,
            two.provider_event_uri,
        }


def test_revocation_migration_and_job_exclusion(disposable_postgres, monkeypatch):  # noqa: F811
    engine, env = disposable_postgres

    def alembic(*args):
        return subprocess.run(
            [sys.executable, "-B", "-m", "alembic", *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )

    for args in (
        ("upgrade", "head"),
        ("downgrade", REVISION),
        ("upgrade", "head"),
        ("check",),
    ):
        result = alembic(*args)
        assert result.returncode == 0, result.stderr

    now = revocation.datetime.now(UTC)
    with Session(engine) as db:
        entitlement = create_test_consultation_entitlement(db)
        entitlement.expires_at = now
        entitlement.calendly_share_uri = SHARE
        entitlement_id = entitlement.id
        db.commit()

    started, release = Event(), Event()

    def delete(uri):
        with Session(engine) as db:
            claim = db.get(ConsultationEntitlement, entitlement_id)
            assert claim.calendly_revoke_attempts == 1
            assert claim.calendly_revoke_outcome == "attempt_started"
        started.set()
        assert release.wait(10)

    provider = Mock(side_effect=delete)
    monkeypatch.setattr(revocation, "delete_share", provider)

    def run():
        with Session(engine) as db:
            return revocation.revoke_expired_shares(db, now=now)

    with ThreadPoolExecutor(max_workers=2) as jobs:
        first = jobs.submit(run)
        try:
            assert started.wait(10)
            assert jobs.submit(run).result(10) == {"status": "already_running"}
        finally:
            release.set()
        assert first.result(10)["by_outcome"] == {"revoked": 1}
    assert run()["selected"] == 0
    provider.assert_called_once_with(SHARE)
    blocked = alembic("downgrade", REVISION)
    assert blocked.returncode != 0
    assert "revocation evidence would be lost" in blocked.stderr


def test_consultation_cancellation_migration_and_competing_checks(
    disposable_postgres, monkeypatch  # noqa: F811
):
    from app.services import consultation_cancellation_service as coordination
    from app.services.refund_service import start_full_refund

    engine, env = disposable_postgres

    def migrate(*args):
        return subprocess.run(
            [sys.executable, "-B", "-m", "alembic", *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )

    for args in (
        ("upgrade", "head"),
        ("check",),
        ("downgrade", "197e36fb4bc1"),
        ("upgrade", "head"),
    ):
        result = migrate(*args)
        assert result.returncode == 0, result.stderr
    with Session(engine) as db:
        entitlement = create_test_consultation_entitlement(db)
        sale = entitlement.sale_item.sale
        sale.payment_provider = "lava_top"
        sale.external_payment_id = "concurrent-cancellation"
        entitlement.status = "booked"
        entitlement.provider_event_uri = (
            "https://api.calendly.com/scheduled_events/CLAIM"
        )
        entitlement.provider_invitee_uri = (
            entitlement.provider_event_uri + "/invitees/ONE"
        )
        sale_id, entitlement_id = sale.id, entitlement.id
        db.commit()
        start_full_refund(db, sale_id=sale_id)

    started, release = Event(), Event()

    def verify(*args, **kwargs):
        started.set()
        assert release.wait(10)
        return "elapsed", "/scheduled_events/CLAIM", None

    monkeypatch.setattr(coordination, "_verify_meeting", verify)

    def check():
        with Session(engine) as db:
            return coordination.check_consultation_cancellation(
                db, sale_id, entitlement_id
            )

    with ThreadPoolExecutor(max_workers=2) as jobs:
        first = jobs.submit(check)
        try:
            assert started.wait(10)
            assert not jobs.submit(check).result(10)
        finally:
            release.set()
        assert first.result(10)
    with Session(engine) as db:
        row = db.get(ConsultationEntitlement, entitlement_id).cancellation
        assert row.verified_at is not None
        assert row.provider_outcome == "elapsed"
    blocked = migrate("downgrade", "197e36fb4bc1")
    assert blocked.returncode != 0
    assert "cancellation evidence would be lost" in blocked.stderr
