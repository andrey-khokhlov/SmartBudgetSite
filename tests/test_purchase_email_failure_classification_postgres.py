import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services import purchase_alert_dispatcher_service as dispatcher
from app.models.purchase_delivery_incident import PurchaseDeliveryIncident
from app.models.purchase_delivery_notification import PurchaseDeliveryNotification
from app.services.purchase_delivery_notification_service import (
    materialize_purchase_delivery_notifications,
)

PREVIOUS = "c20d9be51072"
REVISION = "78e0b9842bd1"


@pytest.fixture
def disposable_postgres():
    if os.environ.get("SMARTBUDGET_TEST_POSTGRES_MIGRATIONS") != "1":
        pytest.skip("Set SMARTBUDGET_TEST_POSTGRES_MIGRATIONS=1 for local PostgreSQL")
    base = make_url(settings.DATABASE_URL)
    assert base.get_backend_name() == "postgresql"
    assert base.host in {"localhost", "127.0.0.1", "::1"}
    name = f"email_classification_test_{uuid4().hex[:12]}"
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    url = base.set(database=name)
    engine = create_engine(url)
    try:
        with admin.connect() as connection:
            connection.execute(text(f"CREATE DATABASE {name}"))
        try:
            yield (
                engine,
                dict(
                    os.environ, DATABASE_URL=url.render_as_string(hide_password=False)
                ),
            )
        finally:
            engine.dispose()
            with admin.connect() as connection:
                connection.execute(text(f"DROP DATABASE {name}"))
    finally:
        admin.dispose()


def test_classification_downgrade_is_lossless_or_blocked(disposable_postgres):
    engine, env = disposable_postgres

    def alembic(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )

    def check_alembic(*args):
        result = alembic(*args)
        assert result.returncode == 0, result.stderr

    check_alembic("upgrade", PREVIOUS)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO sales (customer_email, amount, currency, payment_status) "
                "VALUES ('one@example.test', 50, 'RUB', 'paid'), "
                "('two@example.test', 50, 'RUB', 'paid'), "
                "('three@example.test', 50, 'RUB', 'paid')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO purchase_email_deliveries (sale_id, status, attempt_count) "
                "SELECT id, 'pending', 0 FROM sales ORDER BY id"
            )
        )

    check_alembic("upgrade", "65fc4a8e2b13")
    check_alembic("downgrade", PREVIOUS)
    assert "failure_classification" not in {
        column["name"]
        for column in inspect(engine).get_columns("purchase_email_deliveries")
    }
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == PREVIOUS
        )
        assert (
            connection.scalar(text("SELECT count(*) FROM purchase_email_deliveries"))
            == 3
        )
    check_alembic("upgrade", "65fc4a8e2b13")

    classifications = ["transient", "permanent", "unknown"]
    with engine.begin() as connection:
        head_before_downgrade = connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )
        ids = connection.scalars(
            text("SELECT id FROM purchase_email_deliveries ORDER BY id")
        ).all()
        assert len(ids) == len(classifications)
        for delivery_id, classification in zip(ids, classifications, strict=True):
            connection.execute(
                text(
                    "UPDATE purchase_email_deliveries SET status = 'failed', "
                    "failure_classification = :classification WHERE id = :id"
                ),
                {"id": delivery_id, "classification": classification},
            )

    blocked = alembic("downgrade", PREVIOUS)
    assert blocked.returncode != 0
    assert (
        "Downgrade blocked: purchase email failure classifications would be lost."
        in blocked.stderr
    )
    assert "archive and explicitly migrate the classifications" in blocked.stderr
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == head_before_downgrade
        )
        rows = connection.execute(
            text(
                "SELECT id, status, failure_classification "
                "FROM purchase_email_deliveries ORDER BY id"
            )
        ).all()
        assert rows == list(zip(ids, ["failed"] * 3, classifications, strict=True))


def test_outbox_migration_and_concurrent_materialization(
    disposable_postgres, monkeypatch
):
    engine, env = disposable_postgres
    revision = "b92df68461c0"

    def alembic(*args, blocked=False):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )
        if blocked:
            assert result.returncode != 0
            assert (
                "Downgrade blocked: purchase delivery notification history"
                in result.stderr
            )
        else:
            assert result.returncode == 0, result.stderr

    alembic("upgrade", REVISION)
    alembic("upgrade", revision)
    alembic("downgrade", REVISION)
    assert not inspect(engine).has_table("purchase_delivery_notifications")
    alembic("upgrade", revision)
    alembic("upgrade", "head")
    alembic("check")
    alembic("downgrade", revision)
    alembic("upgrade", "head")

    now = datetime.now(UTC)
    with Session(engine) as db, db.begin():
        incident = PurchaseDeliveryIncident(
            sale_id=1,
            subject_id=1,
            kind="email_failed",
            severity="error",
            first_detected_at=now,
            last_observed_at=now,
        )
        db.add(incident)
        db.flush()
        incident_id = incident.id

    barrier = Barrier(2)

    def materialize():
        with Session(engine) as db:
            barrier.wait(timeout=10)
            return materialize_purchase_delivery_notifications(db)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(materialize) for _ in range(2)]
        assert sorted(result.result(timeout=15) for result in results) == [0, 2]

    with Session(engine) as db:
        db.add(PurchaseDeliveryNotification(incident_id=incident_id, channel="smtp"))
        with pytest.raises(IntegrityError) as duplicate:
            db.commit()
        assert duplicate.value.orig.diag.constraint_name == (
            "uq_purchase_delivery_notifications_incident_channel"
        )
        db.rollback()
        db.delete(db.get(PurchaseDeliveryIncident, incident_id))
        with pytest.raises(IntegrityError):
            db.commit()

    alembic("downgrade", revision)
    alembic("downgrade", REVISION, blocked=True)
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == revision
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM purchase_delivery_notifications")
            )
            == 2
        )

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE purchase_delivery_notifications SET delivered_at = now(), attempt_count = 1 "
                "WHERE channel = 'smtp'"
            )
        )
    alembic("upgrade", "head")
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT status FROM purchase_delivery_notifications WHERE channel = 'smtp'"
                )
            )
            == "delivered"
        )
    # Start dispatch with both channels pending in the scratch database.
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE purchase_delivery_notifications SET status = 'pending', delivered_at = NULL"
            )
        )
    monkeypatch.setattr(settings, "PURCHASE_ALERT_DELIVERY_ENABLED", True)

    def dispatch():
        with Session(engine) as db:
            return dispatcher.dispatch_purchase_alerts(db)

    def telegram(message):
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert (
                pool.submit(dispatch).result(timeout=10)["status"] == "already_running"
            )
        return None

    def unexpected_smtp(message):
        pytest.fail("SMTP must be skipped after Telegram accepts")

    monkeypatch.setattr(dispatcher, "send_telegram_alert", telegram)
    monkeypatch.setattr(dispatcher, "send_smtp_alert", unexpected_smtp)
    assert dispatch()["by_result"] == {"delivered": 1}
    with engine.connect() as connection:
        head_before_downgrade = connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )
    blocked = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", revision],
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert blocked.returncode != 0
    assert "Downgrade blocked: notification dispatcher state" in blocked.stderr
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == head_before_downgrade
        )
        assert connection.execute(
            text(
                "SELECT channel, status FROM purchase_delivery_notifications ORDER BY channel"
            )
        ).all() == [("smtp", "skipped"), ("telegram", "delivered")]
    alembic("check")

def test_sale_paid_at_migration_preserves_payment_history(disposable_postgres):
    engine, env = disposable_postgres
    previous = "d7e45fa921c0"
    revision = "65fc4a8e2b13"

    def alembic(*args, success=True):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert (result.returncode == 0) is success, result.stderr
        return result

    alembic("upgrade", previous)
    with engine.begin() as connection:
        sales = connection.execute(text("""
            INSERT INTO sales (customer_email, amount, currency, payment_status)
            VALUES ('paid@example.test', 50, 'RUB', 'paid'),
                   ('pending@example.test', 50, 'RUB', 'pending'),
                   ('failed@example.test', 50, 'RUB', 'failed')
            RETURNING id, payment_status
        """)).all()

    alembic("upgrade", revision)
    columns = {column["name"]: column for column in inspect(engine).get_columns("sales")}
    assert columns["paid_at"]["nullable"]
    assert columns["paid_at"]["type"].timezone
    assert columns["paid_at"]["default"] is None
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT id, payment_status, paid_at FROM sales ORDER BY id")
        ).all() == [(sale.id, sale.payment_status, None) for sale in sales]

    alembic("downgrade", previous)
    assert "paid_at" not in {
        column["name"] for column in inspect(engine).get_columns("sales")
    }
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT id, payment_status FROM sales ORDER BY id")
        ).all() == sales

    alembic("upgrade", revision)
    paid_at = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE sales SET paid_at = :paid_at WHERE payment_status = 'paid'"),
            {"paid_at": paid_at},
        )

    blocked = alembic("downgrade", previous, success=False)
    assert "Downgrade blocked: Sale payment timestamps would be lost." in blocked.stderr
    with engine.connect() as connection:
        connection.execute(text("SET LOCAL TIME ZONE 'UTC'"))
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == revision
        stored = connection.scalar(text("SELECT paid_at FROM sales WHERE payment_status = 'paid'"))
        assert stored == paid_at
        assert stored.utcoffset() == UTC.utcoffset(stored)


def test_sale_reference_migration_backfills_and_enforces_constraints(disposable_postgres):
    from app.core.sale_reference import SALE_REFERENCE_PATTERN

    engine, env = disposable_postgres
    previous = "65fc4a8e2b13"

    def alembic(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )

    for args in [("upgrade", previous), ("upgrade", "head"), ("downgrade", previous)]:
        result = alembic(*args)
        assert result.returncode == 0, result.stderr

    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO sales (customer_email, amount, currency, payment_status, paid_at)
            VALUES ('paid@example.test', 50, 'RUB', 'paid', '2026-11-13 12:00:00+00'),
                   ('pending@example.test', 79, 'EUR', 'pending', NULL),
                   ('failed@example.test', 39, 'EUR', 'failed', NULL)
        """))
        sales_before = connection.execute(text("SELECT * FROM sales ORDER BY id")).all()
        connection.execute(text("""
            INSERT INTO purchase_email_deliveries
                (sale_id, status, attempt_count, sending_started_at)
            SELECT id, 'sending', 1, now() FROM sales WHERE payment_status = 'paid'
        """))

    blocked = alembic("upgrade", "head")
    assert blocked.returncode != 0
    assert "Reconcile sending purchase emails" in blocked.stderr
    with engine.begin() as connection:
        connection.execute(text("""
            UPDATE purchase_email_deliveries SET status = 'reconciliation_required'
        """))

    for args in [("upgrade", "head"), ("check",)]:
        result = alembic(*args)
        assert result.returncode == 0, result.stderr
    with engine.connect() as connection:
        sales_after = connection.execute(text("SELECT * FROM sales ORDER BY id")).all()
        references = {sale.sale_reference for sale in sales_after}
        assert [sale[:-1] for sale in sales_after] == sales_before
        assert len(references) == len(sales_before)
        assert all(SALE_REFERENCE_PATTERN.fullmatch(ref) for ref in references)

    for reference in (None, next(iter(references))):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text("""
                    INSERT INTO sales
                        (customer_email, amount, currency, payment_status, sale_reference)
                    VALUES ('duplicate@example.test', 50, 'RUB', 'pending', :reference)
                """),
                {"reference": reference},
            )
    blocked = alembic("downgrade", previous)
    assert blocked.returncode != 0
    assert "permanent purchase references would be lost" in blocked.stderr
