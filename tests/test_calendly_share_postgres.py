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
from app.services.calendly import share_service as shares
from app.services.webhooks import reconciliation_service as reconciliation
from tests.services.test_calendly_share_service import EVENT_TYPE, share_resource
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

    alembic("upgrade", REVISION)
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
    alembic("upgrade", REVISION)
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
