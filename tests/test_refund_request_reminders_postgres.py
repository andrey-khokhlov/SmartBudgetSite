import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.refund_request_reminder import RefundRequestReminder
from app.services import refund_request_reminder_service as reminders
from app.services.refund_request_service import record_refund_request_action
from tests.test_purchase_email_failure_classification_postgres import (  # noqa: F401
    disposable_postgres,
)

PREVIOUS = "6e4f8c2a9b17"
NOW = datetime(2026, 11, 16, 12, 34, 56, tzinfo=UTC)


def test_reminder_migration_and_concurrent_dispatch(
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
    with engine.begin() as connection:
        request_id = connection.scalar(
            text("""
            WITH sale AS (
                INSERT INTO sales (sale_reference, customer_email, amount, currency, payment_status)
                VALUES ('PAY-AAAAAAAAAAAAAA', 'buyer@example.test', 50, 'EUR', 'paid')
                RETURNING id
            )
            INSERT INTO refund_requests (
                submission_token, sale_id, purchase_reference, customer_email,
                submitted_at, language, composition, status
            )
            SELECT repeat('a', 64), id, 'PAY-AAAAAAAAAAAAAA', 'buyer@example.test',
                   :submitted, 'en', 'product', 'pending'
            FROM sale RETURNING id
        """),
            {"submitted": NOW - timedelta(days=3)},
        )

    alembic("upgrade", "head")
    alembic("check")
    alembic("downgrade", PREVIOUS)
    assert not inspect(engine).has_table("refund_request_reminders")
    alembic("upgrade", "head")

    started, release = Event(), Event()
    monkeypatch.setattr(
        reminders.settings, "REFUND_REQUEST_REMINDER_DELIVERY_ENABLED", True
    )

    def send(*args, **kwargs):
        with Session(engine) as db:
            row = db.query(RefundRequestReminder).one()
            assert row.status == "sending" and row.telegram_attempts == 1
        started.set()
        assert release.wait(10)
        return None

    monkeypatch.setattr(reminders, "send_telegram_alert", send)

    def dispatch(now):
        with Session(engine) as db:
            return reminders.dispatch_refund_request_reminders(db, clock=lambda: now)

    assert dispatch(NOW - timedelta(microseconds=1))["attempted"] == 0
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(dispatch, NOW)
        try:
            assert started.wait(10)
            assert dispatch(NOW)["status"] == "already_running"
            with Session(engine) as db:
                record_refund_request_action(
                    db, request_id=request_id, action="respond"
                )
                record_refund_request_action(db, request_id=request_id, action="close")
        finally:
            release.set()
        assert first.result(timeout=10)["by_result"] == {"delivered": 1}

    assert dispatch(NOW + timedelta(days=1))["attempted"] == 0
    with pytest.raises(IntegrityError, match="uq_refund_request_reminder_cycle"):
        with Session(engine) as db, db.begin():
            db.add(RefundRequestReminder(request_id=request_id, cycle_date=NOW.date()))
    with Session(engine) as db:
        row = db.query(RefundRequestReminder).one()
        assert row.delivered_at == NOW and row.smtp_attempts == 0
    blocked = alembic("downgrade", PREVIOUS, succeeds=False)
    assert (
        "Downgrade blocked: refund request reminder history exists." in blocked.stderr
    )
    alembic("check")
