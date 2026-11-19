import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from time import monotonic, sleep

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.models.purchase_access_recovery import PurchaseAccessRecovery
from app.models.sale import Sale
from app.services.download_entitlement_service import record_download_attempt
from app.services.purchase_access_recovery_service import RecoveryConflictError
from tests.services.test_purchase_access_recovery import (
    create_paid_recovery_sale,
    prepare,
    send,
)
from tests.services.test_purchase_email_delivery_service import (
    RecordingTransport,
    configure_email,
)
from tests.test_purchase_email_failure_classification_postgres import (  # noqa: F401
    disposable_postgres,
)

PREVIOUS = "8e21d4f6ab93"
REVISION = "4a2d8c71ef36"


def test_recovery_migration_and_concurrent_requests(
    disposable_postgres,  # noqa: F811
    monkeypatch,
):
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

    alembic("upgrade", PREVIOUS)
    with Session(engine) as db:
        sale_id = create_paid_recovery_sale(db)
        old_token = db.get(Sale, sale_id).items[0].download_entitlement.download_token
    alembic("upgrade", REVISION)
    alembic("check")
    alembic("downgrade", PREVIOUS)
    assert not inspect(engine).has_table("purchase_access_recoveries")
    alembic("upgrade", REVISION)
    alembic("check")

    start = Barrier(3, timeout=10)

    def prepare_in_session():
        with Session(engine) as db:
            start.wait()
            return prepare(db, sale_id)

    with ThreadPoolExecutor(max_workers=2) as threads, Session(engine) as download:
        assert record_download_attempt(download, old_token).attempt_count == 1
        download_pid = download.scalar(text("SELECT pg_backend_pid()"))
        try:
            first = threads.submit(prepare_in_session)
            duplicate = threads.submit(prepare_in_session)
            start.wait()
            with engine.connect().execution_options(
                isolation_level="AUTOCOMMIT"
            ) as connection:
                blocked = text(
                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                    "WHERE datname = current_database() "
                    "AND :pid = ANY(pg_blocking_pids(pid)))"
                )
                deadline = monotonic() + 5
                while not connection.scalar(blocked, {"pid": download_pid}):
                    assert (
                        monotonic() < deadline
                    ), "Recovery did not wait for the download lock"
                    sleep(0.01)
        finally:
            download.commit()
        assert {first.result(timeout=10), duplicate.result(timeout=10)} == {
            "prepared",
            "already_prepared",
        }

    with Session(engine) as db:
        row = db.query(PurchaseAccessRecovery).one()
        recovery_id = row.id
        grant = db.get(Sale, sale_id).items[0].download_entitlement
        assert row.previous_attempt_count == 1
        assert row.previous_first_attempt_at is not None
        assert grant.attempt_count == 0
        assert grant.download_token != old_token

    configure_email(monkeypatch)
    sending, finish = Event(), Event()

    def pause_in_transport():
        sending.set()
        assert finish.wait(10)

    transport = RecordingTransport(on_send=pause_in_transport)

    def send_in_session():
        with Session(engine) as db:
            return send(db, sale_id, recovery_id, transport)

    with ThreadPoolExecutor(max_workers=1) as threads:
        pending = threads.submit(send_in_session)
        try:
            assert sending.wait(10)
            with Session(engine) as db:
                assert send(db, sale_id, recovery_id, transport) == "sending"
                with pytest.raises(RecoveryConflictError, match="Resolve the existing"):
                    prepare(
                        db,
                        sale_id,
                        request_id="b" * 32,
                        expected_recovery_id=recovery_id,
                    )
        finally:
            finish.set()
        assert pending.result(timeout=10) == "accepted"
    assert len(transport.messages) == 1

    blocked = alembic("downgrade", PREVIOUS, succeeds=False)
    assert (
        "Downgrade blocked: purchase access recovery history exists." in blocked.stderr
    )
    with Session(engine) as db:
        assert db.get(PurchaseAccessRecovery, recovery_id).delivery_status == "accepted"
    alembic("check")
