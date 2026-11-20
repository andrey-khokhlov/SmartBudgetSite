import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from time import monotonic, sleep
from unittest.mock import Mock

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.refund_request import RefundRequest
from app.services import refund_request_service
from tests.test_purchase_email_failure_classification_postgres import (  # noqa: F401
    disposable_postgres,
)

PREVIOUS = "1c6ea8b50d37"
REVISION = "6e4f8c2a9b17"


def test_refund_request_lifecycle_migration_and_row_lock(
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
    submitted = datetime(2026, 11, 16, 10, tzinfo=UTC)
    with engine.begin() as connection:
        sale_id = connection.scalar(
            text("""
            INSERT INTO sales (sale_reference, customer_email, amount, currency, payment_status)
            VALUES ('PAY-AAAAAAAAAAAAAA', 'buyer@example.test', 50, 'EUR', 'paid')
            RETURNING id
        """)
        )
        request_id = connection.scalar(
            text("""
            INSERT INTO refund_requests (
                submission_token, sale_id, purchase_reference, customer_email,
                submitted_at, language, composition, status
            )
            VALUES (
                repeat('a', 64), :sale_id, 'PAY-AAAAAAAAAAAAAA', 'buyer@example.test',
                :submitted, 'en', 'product', 'pending'
            )
            RETURNING id
        """),
            {"sale_id": sale_id, "submitted": submitted},
        )

    alembic("upgrade", REVISION)
    alembic("check")
    columns = {
        column["name"]: column
        for column in inspect(engine).get_columns("refund_requests")
    }
    for name in ("first_responded_at", "closed_at"):
        assert columns[name]["type"].timezone is True
        assert columns[name]["nullable"] is True and columns[name]["default"] is None

    alembic("downgrade", PREVIOUS)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT id FROM refund_requests")) == request_id
    alembic("upgrade", REVISION)
    with Session(engine) as db:
        entry = db.get(RefundRequest, request_id)
        assert entry.submitted_at == submitted
        assert entry.status == "pending"
        assert entry.first_responded_at is None and entry.closed_at is None
    with pytest.raises(IntegrityError, match="ck_refund_requests_lifecycle"):
        with engine.begin() as connection:
            connection.execute(text("UPDATE refund_requests SET status = 'closed'"))

    responded = submitted + timedelta(days=1)
    closed = responded + timedelta(days=1)
    clock = Mock(side_effect=[responded, closed])
    monkeypatch.setattr(refund_request_service, "datetime", Mock(now=clock))

    def record(action):
        with Session(engine) as db:
            refund_request_service.record_refund_request_action(
                db, request_id=request_id, action=action
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        with engine.begin() as lock:
            lock.execute(
                text("SELECT id FROM refund_requests WHERE id = :id FOR UPDATE"),
                {"id": request_id},
            )
            locker_pid = lock.scalar(text("SELECT pg_backend_pid()"))
            first = pool.submit(record, "respond")
            duplicate = pool.submit(record, "respond")
            with engine.connect().execution_options(
                isolation_level="AUTOCOMMIT"
            ) as observer:
                blocked = text("""
                    SELECT EXISTS (
                        SELECT 1 FROM pg_stat_activity
                        WHERE datname = current_database()
                          AND :pid = ANY(pg_blocking_pids(pid))
                    )
                """)
                deadline = monotonic() + 5
                while not observer.scalar(blocked, {"pid": locker_pid}):
                    assert monotonic() < deadline, (
                        "Refund request action did not wait for the row lock"
                    )
                    sleep(0.01)
        first.result(timeout=10)
        duplicate.result(timeout=10)
        assert clock.call_count == 1
        closure = pool.submit(record, "close")
        duplicate = pool.submit(record, "close")
        closure.result(timeout=10)
        duplicate.result(timeout=10)
        assert clock.call_count == 2

    blocked = alembic("downgrade", PREVIOUS, succeeds=False)
    assert (
        "Downgrade blocked: refund request lifecycle history exists." in blocked.stderr
    )
    alembic("check")
    with Session(engine) as db:
        entry = db.get(RefundRequest, request_id)
        assert entry.status == "closed"
        assert entry.submitted_at == submitted
        assert entry.first_responded_at == responded
        assert entry.closed_at == closed
