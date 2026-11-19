import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.consultation_capacity import (
    ConsultationCapacityNotification,
    ConsultationCapacityState,
)
from app.models.sale import Sale
from app.services import consultation_capacity_alert_service as alerts
from app.services.consultation_capacity_service import (
    get_consultation_capacity,
    set_consultation_sales_suspended,
)
from tests.services.test_consultation_capacity import add_available_rights
from tests.test_purchase_email_failure_classification_postgres import (  # noqa: F401
    disposable_postgres,
)

PREVIOUS = "5c2c71bc5f4a"


def test_capacity_migration_and_concurrent_dispatch(
    disposable_postgres,  # noqa: F811
    monkeypatch,
):
    engine, env = disposable_postgres

    def alembic(*args):
        result = subprocess.run(
            [sys.executable, "-B", "-m", "alembic", *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert result.returncode == 0, result.stderr

    alembic("upgrade", PREVIOUS)
    with Session(engine) as db:
        add_available_rights(db, 4)
    alembic("upgrade", "head")
    alembic("check")

    with Session(engine) as db:
        snapshot = get_consultation_capacity(db)
        assert snapshot.outstanding == 4
        assert not snapshot.manually_suspended
        assert not snapshot.available
        assert db.get(ConsultationCapacityState, 1).observed_level == "normal"

    monkeypatch.setattr(settings, "CONSULTATION_CAPACITY_ALERT_DELIVERY_ENABLED", True)
    sending, finish = Event(), Event()

    def telegram(message):
        assert "exhausted" in message
        sending.set()
        assert finish.wait(10)

    monkeypatch.setattr(alerts, "send_telegram_alert", telegram)

    def dispatch():
        with Session(engine) as db:
            return alerts.dispatch_consultation_capacity_alerts(db)

    with ThreadPoolExecutor(max_workers=1) as threads:
        first = threads.submit(dispatch)
        try:
            assert sending.wait(10)
            assert dispatch()["status"] == "already_running"
            with Session(engine) as db:
                set_consultation_sales_suspended(db, suspended=True)
        finally:
            finish.set()
        assert first.result(timeout=10)["by_result"] == {"delivered": 1}

    with Session(engine) as db:
        assert get_consultation_capacity(db).manually_suspended
        rows = db.query(ConsultationCapacityNotification).all()
        assert len(rows) == 2
        assert len({row.episode_id for row in rows}) == 1

    alembic("downgrade", PREVIOUS)
    assert not inspect(engine).has_table("consultation_capacity_state")
    assert not inspect(engine).has_table("consultation_capacity_notifications")
    with Session(engine) as db:
        assert db.query(Sale).count() == 4
    alembic("upgrade", "head")
    alembic("check")
