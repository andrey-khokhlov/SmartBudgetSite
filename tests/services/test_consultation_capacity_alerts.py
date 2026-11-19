import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from app.core.config import settings
from app.models.consultation_capacity import (
    ConsultationCapacityNotification,
    ConsultationCapacityState,
)
from app.services import consultation_capacity_alert_service as alerts
from app.services import purchase_alert_dispatcher_service as purchase_alerts
from scripts.dispatch_purchase_alerts import main
from tests.services.test_consultation_capacity import add_available_rights


@pytest.fixture
def transports(db_session, monkeypatch):
    def no_transaction(*args, **kwargs):
        assert not db_session.in_transaction()

    telegram, smtp = Mock(side_effect=no_transaction), Mock(side_effect=no_transaction)
    monkeypatch.setattr(alerts, "send_telegram_alert", telegram)
    monkeypatch.setattr(alerts, "send_smtp_alert", smtp)
    monkeypatch.setattr(settings, "CONSULTATION_CAPACITY_ALERT_DELIVERY_ENABLED", True)
    return telegram, smtp


def test_warning_and_exhaustion_are_deduplicated_and_rearm(db_session, transports):
    rights = add_available_rights(db_session, 5)
    rights[2].status = rights[3].status = rights[4].status = "booked"
    db_session.commit()
    telegram, smtp = transports
    samples = [
        (None, None, 0),  # Two is normal.
        (2, "available", 1),  # Three crosses the warning threshold.
        (None, None, 0),
        (3, "available", 1),  # Four crosses the limit.
        (4, "available", 0),  # Five stays exhausted.
        (4, "booked", 0),
        (3, "booked", 0),  # Falling to warning does not raise a warning.
        (3, "available", 1),  # Falling below four rearmed exhaustion.
        (3, "booked", 0),
        (2, "booked", 0),  # Falling below three rearms the warning.
        (2, "available", 1),
    ]
    for index, (right, status, created) in enumerate(samples):
        if right is not None:
            rights[right].status = status
        db_session.commit()
        result = alerts.dispatch_consultation_capacity_alerts(db_session)
        assert result["materialized"] == result["attempted"] == created, index
    assert telegram.call_count == 4
    messages = [call.args[0] for call in telegram.call_args_list]
    assert [message.splitlines()[0].split()[-1] for message in messages] == [
        "warning",
        "exhausted",
        "exhausted",
        "warning",
    ]
    assert all("buyer@example.com" not in message for message in messages)
    smtp.assert_not_called()
    rows = db_session.query(ConsultationCapacityNotification).all()
    assert len({row.episode_id for row in rows}) == 4
    assert {(row.channel, row.status, row.attempt_count) for row in rows} == {
        ("telegram", "delivered", 1),
        ("smtp", "skipped", 0),
    }


def test_unconfirmed_telegram_falls_back_to_smtp_and_retries(db_session, transports):
    now = datetime.now(UTC)
    add_available_rights(db_session, 4)
    telegram, smtp = transports
    telegram.side_effect = ["ambiguous", "temporary"]
    smtp.side_effect = ["temporary", None]
    first = alerts.dispatch_consultation_capacity_alerts(db_session, clock=lambda: now)
    assert first["materialized"] == 1
    assert first["by_result"] == {"pending": 2}
    assert (
        alerts.dispatch_consultation_capacity_alerts(
            db_session, clock=lambda: now + timedelta(seconds=59)
        )["attempted"]
        == 0
    )
    later = now + timedelta(minutes=1)
    assert alerts.dispatch_consultation_capacity_alerts(
        db_session, clock=lambda: later
    )["by_result"] == {"pending": 1, "delivered": 1}
    assert smtp.call_args.kwargs == {"subject": "SmartBudget consultation capacity"}
    assert telegram.call_count == smtp.call_count == 2
    rows = db_session.query(ConsultationCapacityNotification).all()
    assert {
        (row.channel, row.status, row.attempt_count, row.last_error) for row in rows
    } == {
        ("telegram", "skipped", 2, "temporary"),
        ("smtp", "delivered", 2, "temporary"),
    }
    assert all(row.last_attempt_at is not None for row in rows)
    assert next(row for row in rows if row.channel == "smtp").delivered_at is not None


def test_interrupted_send_recovers_after_lease_without_reinserting_event(
    db_session, transports
):
    now = datetime.now(UTC)
    add_available_rights(db_session, 3)
    telegram, smtp = transports
    telegram.side_effect = RuntimeError("process interrupted during delivery")
    with pytest.raises(RuntimeError, match="interrupted"):
        alerts.dispatch_consultation_capacity_alerts(db_session, clock=lambda: now)
    assert (
        alerts.dispatch_consultation_capacity_alerts(
            db_session, clock=lambda: now + timedelta(seconds=119)
        )["attempted"]
        == 0
    )
    result = alerts.dispatch_consultation_capacity_alerts(
        db_session, clock=lambda: now + alerts.SEND_LEASE
    )
    assert result["materialized"] == 0
    assert result["by_result"] == {"delivered": 1}
    telegram.assert_called_once()
    smtp.assert_called_once()
    rows = db_session.query(ConsultationCapacityNotification).all()
    assert {
        (row.channel, row.status, row.attempt_count, row.last_error) for row in rows
    } == {
        ("telegram", "skipped", 1, "ambiguous"),
        ("smtp", "delivered", 1, None),
    }


def test_dry_run_and_disabled_dispatch_are_read_only(
    db_session, transports, monkeypatch
):
    add_available_rights(db_session, 3)
    monkeypatch.setattr(settings, "CONSULTATION_CAPACITY_ALERT_DELIVERY_ENABLED", False)
    assert (
        alerts.dispatch_consultation_capacity_alerts(db_session)["status"] == "disabled"
    )
    assert (
        alerts.dispatch_consultation_capacity_alerts(db_session, dry_run=True)["status"]
        == "dry_run"
    )
    assert db_session.get(ConsultationCapacityState, 1).observed_level == "normal"
    assert db_session.query(ConsultationCapacityNotification).count() == 0
    for transport in transports:
        transport.assert_not_called()


@pytest.mark.parametrize("failure", ["purchase_alert", "consultation_capacity"])
def test_scheduled_dispatch_passes_have_independent_sessions(
    failure, capsys, monkeypatch
):
    purchase = Mock(return_value={"status": "completed"})
    capacity = Mock(return_value={"status": "completed"})
    {"purchase_alert": purchase, "consultation_capacity": capacity}[
        failure
    ].side_effect = RuntimeError("private provider evidence")
    monkeypatch.setattr(purchase_alerts, "dispatch_purchase_alerts", purchase)
    monkeypatch.setattr(alerts, "dispatch_consultation_capacity_alerts", capacity)
    assert main(["--dry-run"]) == 1
    output = capsys.readouterr()
    assert json.loads(output.err) == {"error": f"{failure}_dispatch_failed"}
    result = json.loads(output.out)
    assert result["status"] == ("error" if failure == "purchase_alert" else "completed")
    assert result["consultation_capacity"]["status"] == (
        "error" if failure == "consultation_capacity" else "completed"
    )
    assert purchase.call_args.args[0] is not capacity.call_args.args[0]
    assert purchase.call_args.kwargs == capacity.call_args.kwargs == {"dry_run": True}
