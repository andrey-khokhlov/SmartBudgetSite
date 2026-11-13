import smtplib
import ssl
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, select

from app.core.config import settings
from app.models.purchase_delivery_incident import PurchaseDeliveryIncident
from app.models.purchase_delivery_notification import PurchaseDeliveryNotification
from app.services import purchase_alert_dispatcher_service as dispatcher
from app.services import purchase_alert_transport as transport
from app.services.purchase_delivery_notification_service import (
    materialize_purchase_delivery_notifications,
)

NOW = datetime(2030, 1, 1, tzinfo=UTC)


@pytest.fixture
def incident(db_session, monkeypatch):
    monkeypatch.setattr(settings, "PURCHASE_ALERT_DELIVERY_ENABLED", True)
    incident = PurchaseDeliveryIncident(
        sale_id=1,
        subject_id=1,
        kind="email_failed",
        severity="error",
        first_detected_at=NOW,
        last_observed_at=NOW,
    )
    db_session.add(incident)
    db_session.commit()
    return incident


def rows(db):
    return {
        row.channel: row for row in db.scalars(select(PurchaseDeliveryNotification))
    }


def fake_senders(monkeypatch, db, *, telegram=None, smtp=None):
    calls = []

    def sender(channel, result):
        def send(message):
            assert not db.in_transaction()
            assert "SmartBudget incident #" in message
            calls.append(channel)
            return result

        return send

    monkeypatch.setattr(dispatcher, "send_telegram_alert", sender("telegram", telegram))
    monkeypatch.setattr(dispatcher, "send_smtp_alert", sender("smtp", smtp))
    return calls


@pytest.mark.parametrize(
    "telegram_error", [None, "temporary", "ambiguous", "configuration"]
)
def test_success_suppresses_other_channel(
    db_session, incident, monkeypatch, telegram_error
):
    calls = fake_senders(monkeypatch, db_session, telegram=telegram_error)
    dispatcher.dispatch_purchase_alerts(db_session, clock=lambda: NOW)
    entries = rows(db_session)
    winner = "telegram" if telegram_error is None else "smtp"
    loser = "smtp" if winner == "telegram" else "telegram"
    assert calls == (["telegram"] if telegram_error is None else ["telegram", "smtp"])
    assert entries[winner].status == "delivered"
    assert entries[loser].status == "skipped"
    assert entries[loser].delivered_at is None
    assert entries[loser].skip_reason == "other_channel_succeeded"
    assert entries["telegram"].last_error == telegram_error
    db_session.rollback()
    assert (
        dispatcher.dispatch_purchase_alerts(db_session, clock=lambda: NOW)["attempted"]
        == 0
    )


def test_divergent_deadlines_honor_each_channels_backoff(
    db_session, incident, monkeypatch
):
    calls = fake_senders(
        monkeypatch, db_session, telegram="temporary", smtp="temporary"
    )
    dispatcher.dispatch_purchase_alerts(db_session, clock=lambda: NOW)
    entries = rows(db_session)
    assert calls == ["telegram", "smtp"]
    assert all(
        row.next_attempt_at.replace(tzinfo=UTC) == NOW + timedelta(minutes=1)
        for row in entries.values()
    )
    entries["smtp"].next_attempt_at = NOW + timedelta(minutes=2)
    db_session.commit()
    dispatcher.dispatch_purchase_alerts(
        db_session, clock=lambda: NOW + timedelta(minutes=1)
    )
    assert calls == ["telegram", "smtp", "telegram"]
    dispatcher.dispatch_purchase_alerts(
        db_session, clock=lambda: NOW + timedelta(minutes=2)
    )
    assert calls == ["telegram", "smtp", "telegram", "smtp"]
    assert rows(db_session)["telegram"].next_attempt_at.replace(
        tzinfo=UTC
    ) == NOW + timedelta(minutes=3)


@pytest.mark.parametrize("smtp_error", ["permanent", "temporary"])
def test_permanent_channel_does_not_retry(
    db_session, incident, monkeypatch, smtp_error
):
    calls = fake_senders(
        monkeypatch, db_session, telegram="configuration", smtp=smtp_error
    )
    dispatcher.dispatch_purchase_alerts(db_session, clock=lambda: NOW)
    dispatcher.dispatch_purchase_alerts(
        db_session, clock=lambda: NOW + timedelta(minutes=1)
    )
    assert calls == (
        ["telegram", "smtp"]
        if smtp_error == "permanent"
        else ["telegram", "smtp", "smtp"]
    )
    assert rows(db_session)["telegram"].status == "failed"


def test_recheck_incident_before_fallback(db_session, incident, monkeypatch):
    calls = fake_senders(monkeypatch, db_session)

    def resolve(_):
        assert not db_session.in_transaction()
        incident.resolved_at = NOW
        db_session.commit()
        return "temporary"

    monkeypatch.setattr(dispatcher, "send_telegram_alert", resolve)
    dispatcher.dispatch_purchase_alerts(db_session, clock=lambda: NOW)
    assert calls == []
    entries = rows(db_session)
    assert all(
        row.status == "skipped" and row.skip_reason == "incident_resolved"
        for row in entries.values()
    )
    assert entries["telegram"].attempt_count == 1
    assert entries["telegram"].last_error == "temporary"


def test_expired_claim_is_recoverable_and_fences_old_completion(
    db_session, incident, monkeypatch
):
    incident_id = incident.id
    db_session.rollback()
    materialize_purchase_delivery_notifications(db_session)
    abandoned = dispatcher._claim(
        db_session, incident_id, clock=lambda: NOW, attempted=set()
    )
    calls = fake_senders(monkeypatch, db_session)
    assert (
        dispatcher.dispatch_purchase_alerts(db_session, clock=lambda: NOW)["attempted"]
        == 0
    )
    later = NOW + dispatcher.SEND_LEASE
    dispatcher.dispatch_purchase_alerts(db_session, clock=lambda: later)
    assert calls == ["telegram"]
    assert (
        dispatcher._finish(
            db_session, incident_id, abandoned, "temporary", clock=lambda: later
        )
        == "stale_claim"
    )
    assert rows(db_session)["telegram"].attempt_count == 2


def test_dry_run_and_disabled_mode_do_not_materialize_or_send(
    db_session, incident, monkeypatch
):
    calls = fake_senders(monkeypatch, db_session)
    assert (
        dispatcher.dispatch_purchase_alerts(db_session, dry_run=True)["status"]
        == "dry_run"
    )
    monkeypatch.setattr(settings, "PURCHASE_ALERT_DELIVERY_ENABLED", False)
    assert dispatcher.dispatch_purchase_alerts(db_session)["status"] == "disabled"
    assert not calls and not rows(db_session)


def test_failed_claim_commit_never_sends(db_session, incident, monkeypatch):
    incident_id = incident.id
    db_session.rollback()
    materialize_purchase_delivery_notifications(db_session)

    def fail_commit(session):
        raise RuntimeError("claim failed")

    event.listen(db_session, "before_commit", fail_commit, once=True)
    with pytest.raises(RuntimeError, match="claim failed"):
        dispatcher._claim(db_session, incident_id, clock=lambda: NOW, attempted=set())
    assert all(
        row.status == "pending" and row.attempt_count == 0
        for row in rows(db_session).values()
    )


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (200, b'{"ok":true}', None),
        (200, b'{"ok":false}', "ambiguous"),
        (200, b"malformed", "ambiguous"),
        (429, b"", "temporary"),
        (403, b"", "permanent"),
    ],
)
def test_telegram_adapter_classifies_responses(monkeypatch, status, body, expected):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "123:fake")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "456")

    class FakeConnection:
        def __init__(self, host, *, timeout):
            assert timeout == transport.NETWORK_TIMEOUT

        def request(self, method, path, *, body, headers):
            assert method == "POST"

        def getresponse(self):
            self.status = status
            return self

        def read(self, maximum):
            return body

        def close(self):
            pass

    monkeypatch.setattr(transport, "HTTPSConnection", FakeConnection)
    assert transport.send_telegram_alert("test message") == expected


@pytest.mark.parametrize(
    "tls_failure", [None, "disabled", "unsupported", "certificate", "timeout"]
)
def test_smtp_requires_verified_starttls_before_auth(monkeypatch, tls_failure):
    for field, value in {
        "MAIL_SMTP_HOST": "smtp.example.test",
        "MAIL_SMTP_USER": "private-user",
        "MAIL_SMTP_PASSWORD": "private-password",
        "MAIL_FROM_EMAIL": "sender@example.test",
        "ADMIN_NOTIFICATION_EMAIL": "ops@example.test",
        "MAIL_SMTP_TLS": tls_failure != "disabled",
    }.items():
        monkeypatch.setattr(settings, field, value)
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, *, timeout):
            assert host == "smtp.example.test"
            assert timeout == transport.NETWORK_TIMEOUT
            calls.append("connect")

        def starttls(self, *, context):
            assert context.verify_mode == ssl.CERT_REQUIRED
            assert context.check_hostname
            calls.append("starttls")
            if tls_failure == "unsupported":
                raise smtplib.SMTPNotSupportedError("private response")
            if tls_failure == "certificate":
                raise ssl.SSLCertVerificationError("private certificate details")
            if tls_failure == "timeout":
                raise TimeoutError("private host")

        def login(self, user, password):
            assert calls == ["connect", "starttls"]
            calls.append("login")

        def send_message(self, message):
            calls.append("send")
            assert message.get_content().strip() == "test alert"

        def close(self):
            calls.append("close")
            raise OSError("private shutdown failure")

    monkeypatch.setattr(transport.smtplib, "SMTP", FakeSMTP)
    result = transport.send_smtp_alert("test alert")
    if tls_failure is None:
        assert result is None
        assert calls == ["connect", "starttls", "login", "send", "close"]
    elif tls_failure == "disabled":
        assert result == "configuration"
        assert calls == []
    else:
        assert result == ("ambiguous" if tls_failure == "timeout" else "configuration")
        assert calls == ["connect", "starttls", "close"]


def test_both_channels_receive_only_incident_metadata(
    db_session, incident, monkeypatch
):
    incident.resolution_reason = (
        "buyer@example.test https://example.test/private token123"
    )
    incident.resolved_by = "private-operator"
    incident.originating_event_id = "private-provider-value"
    incident_id = incident.id
    db_session.commit()
    messages = {}

    def telegram(message):
        messages["telegram"] = message
        return "temporary"

    def smtp(message):
        messages["smtp"] = message
        return None

    monkeypatch.setattr(dispatcher, "send_telegram_alert", telegram)
    monkeypatch.setattr(dispatcher, "send_smtp_alert", smtp)
    dispatcher.dispatch_purchase_alerts(db_session, clock=lambda: NOW)

    expected = f"SmartBudget incident #{incident_id} · email_failed · error\nFirst detected {NOW.isoformat()}"
    assert messages == {"telegram": expected, "smtp": expected}
