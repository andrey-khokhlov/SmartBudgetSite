import base64
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from svix.webhooks import Webhook

from app.core.config import settings
from app.models.purchase_delivery_incident import PurchaseDeliveryIncident
from app.models.purchase_email_delivery import PurchaseEmailDelivery
from app.models.resend_webhook_event import ResendWebhookEvent
from app.models.sale import Sale
from app.services.email_transport import EmailTransportResult
from app.services.purchase_delivery_monitoring_service import (
    resolve_operator_incident,
    scan_purchase_delivery,
)
from app.services.purchase_email_delivery_service import attempt_purchase_email_delivery
from scripts.resolve_purchase_delivery_incident import main as resolve_main

URL = "/v1/webhooks/resend"
SECRET = "whsec_" + base64.b64encode(b"test-only-svix-secret").decode()
EVENT_TIME = datetime(2026, 11, 12, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def set_secret(monkeypatch):
    monkeypatch.setattr(settings, "RESEND_WEBHOOK_SIGNING_SECRET", SECRET)


def make_delivery(db, provider_id="provider-email"):
    delivery = PurchaseEmailDelivery(
        sale=Sale(
            customer_email="private@example.test",
            amount=Decimal("50.00"),
            currency="RUB",
            payment_status="paid",
        ),
        provider_message_id=provider_id,
        status="sent" if provider_id else "pending",
    )
    db.add(delivery)
    db.flush()
    delivery_id = delivery.id
    sale_id = delivery.sale.id
    db.commit()
    return delivery_id, sale_id


def event(kind, *, delivery_id=None, provider_id="provider-email", at=EVENT_TIME):
    return json.dumps(
        {
            "type": kind,
            "created_at": at.isoformat(),
            "data": {
                "email_id": provider_id,
                "created_at": (EVENT_TIME + timedelta(days=100)).isoformat(),
                "to": ["private@example.test"],
                "subject": "private capability token",
                "tags": {}
                if delivery_id is None
                else {
                    "purchase_email_delivery_id": str(delivery_id),
                },
            },
        }
    )


def send(client, svix_id, body, *, signature_time=None, changed_body=None):
    signed_at = signature_time or datetime.now(UTC)
    headers = {
        "svix-id": svix_id,
        "svix-timestamp": str(int(signed_at.timestamp())),
        "svix-signature": Webhook(SECRET).sign(svix_id, signed_at, body),
    }
    return client.post(
        URL, headers=headers, content=body if changed_body is None else changed_body
    )


def test_signature_validation_and_bounded_body(client, db_session):
    body = event("email.delivered")
    assert send(client, "msg_invalid", body, changed_body=body + " ").status_code == 401
    assert (
        send(
            client,
            "msg_stale",
            body,
            signature_time=datetime.now(UTC) - timedelta(minutes=6),
        ).status_code
        == 401
    )
    assert client.post(URL, content="x" * (64 * 1024 + 1)).status_code == 413
    assert client.post(URL, content=body).status_code == 401
    assert db_session.query(ResendWebhookEvent).count() == 0
    assert send(client, "msg_valid", body + " ").status_code == 204
    db_session.expire_all()
    assert db_session.get(ResendWebhookEvent, "msg_valid").outcome == "unmatched"


@pytest.mark.parametrize(
    ("body", "outcome"),
    [("{", "malformed"), ("[]", "malformed"), (event("email.opened"), "unsupported")],
)
def test_signed_bad_events_are_acknowledged_without_payload(
    client, db_session, body, outcome
):
    assert send(client, "msg_bad", body).status_code == 204
    receipt = db_session.get(ResendWebhookEvent, "msg_bad")
    assert receipt.outcome == outcome
    assert receipt.event_type is None
    assert receipt.provider_email_id is None
    assert receipt.provider_event_at is None


def test_delivery_ordering_legacy_fallback_and_complaint(client, db_session):
    delivery_id, _ = make_delivery(db_session)
    delivered_at = EVENT_TIME + timedelta(minutes=1)
    assert (
        send(
            client, "msg_delivered", event("email.delivered", at=delivered_at)
        ).status_code
        == 204
    )
    assert (
        send(
            client, "msg_older", event("email.sent", delivery_id=delivery_id)
        ).status_code
        == 204
    )
    complaint = event("email.complained", delivery_id=delivery_id, at=delivered_at)
    for svix_id in ("msg_complaint", "msg_complaint", "msg_complaint_replay"):
        assert send(client, svix_id, complaint).status_code == 204
    delivery = db_session.get(PurchaseEmailDelivery, delivery_id)
    assert delivery.provider_delivery_status == "delivered"
    assert delivery.provider_event_at.replace(tzinfo=UTC) == delivered_at
    assert delivery.provider_event_id == "msg_delivered"
    assert delivery.complaint_event_id == "msg_complaint"
    assert delivery.status == "sent"
    assert db_session.get(ResendWebhookEvent, "msg_older").outcome == "not_newer"
    assert db_session.query(ResendWebhookEvent).count() == 4
    incident = db_session.query(PurchaseDeliveryIncident).one()
    assert incident.requires_operator
    assert incident.kind == "email_provider_complaint"


@pytest.mark.parametrize("matches", [True, False])
def test_send_completion_resolves_deferred_correlation(
    client, db_session, monkeypatch, matches
):
    delivery_id, sale_id = make_delivery(db_session, provider_id=None)
    monkeypatch.setattr(
        "app.services.purchase_email_delivery_service._build_transactional_email",
        lambda *args, **kwargs: None,
    )

    class Transport:
        def send(self, message):
            provider_id = "provider-email" if matches else "different-email"
            assert (
                send(
                    client,
                    "msg_race",
                    event(
                        "email.bounced",
                        delivery_id=delivery_id,
                        provider_id=provider_id,
                    ),
                ).status_code
                == 204
            )
            receipt = db_session.get(ResendWebhookEvent, "msg_race")
            assert receipt.outcome == "awaiting_provider_confirmation"
            assert db_session.query(PurchaseDeliveryIncident).count() == 0
            assert (
                db_session.get(
                    PurchaseEmailDelivery, delivery_id
                ).provider_delivery_status
                is None
            )
            db_session.rollback()
            return EmailTransportResult("provider-email")

    assert (
        attempt_purchase_email_delivery(
            db_session, sale_id=sale_id, transport=Transport()
        )
        == "sent"
    )
    delivery = db_session.get(PurchaseEmailDelivery, delivery_id)
    assert delivery.provider_message_id == "provider-email"
    assert delivery.provider_delivery_status == ("bounced" if matches else None)
    assert delivery.complaint_at is None
    receipt = db_session.get(ResendWebhookEvent, "msg_race")
    assert receipt.outcome == ("applied" if matches else "correlation_conflict")
    incident = db_session.query(PurchaseDeliveryIncident).one()
    assert incident.requires_operator
    assert incident.originating_event_id == "msg_race"
    assert incident.kind == (
        "email_provider_bounced" if matches else "email_provider_correlation_conflict"
    )


def test_older_terminal_event_opens_incident_without_replacing_delivered_state(
    client, db_session
):
    delivery_id, _ = make_delivery(db_session)
    delivered_at = EVENT_TIME + timedelta(minutes=1)
    delivered = event("email.delivered", delivery_id=delivery_id, at=delivered_at)
    assert send(client, "msg_delivered", delivered).status_code == 204
    bounced = event("email.bounced", delivery_id=delivery_id)
    for svix_id in ("msg_older_bounce", "msg_older_bounce", "msg_older_bounce_replay"):
        assert send(client, svix_id, bounced).status_code == 204

    delivery = db_session.get(PurchaseEmailDelivery, delivery_id)
    assert delivery.provider_delivery_status == "delivered"
    assert delivery.provider_event_id == "msg_delivered"
    assert delivery.provider_event_at.replace(tzinfo=UTC) == delivered_at
    assert delivery.complaint_at is None
    assert db_session.get(ResendWebhookEvent, "msg_older_bounce").outcome == "not_newer"
    incident = db_session.query(PurchaseDeliveryIncident).one()
    assert incident.kind == "email_provider_bounced"
    assert incident.requires_operator
    assert incident.originating_event_id == "msg_older_bounce"


def test_send_completion_recovers_untagged_receipt_by_exact_provider_id(
    client, db_session, monkeypatch
):
    delivery_id, sale_id = make_delivery(db_session, provider_id=None)
    assert send(client, "msg_legacy", event("email.bounced")).status_code == 204
    assert (
        send(
            client, "msg_other", event("email.bounced", provider_id="other")
        ).status_code
        == 204
    )
    assert (
        send(
            client, "msg_other_tag", event("email.bounced", delivery_id=delivery_id + 1)
        ).status_code
        == 204
    )
    legacy = db_session.get(ResendWebhookEvent, "msg_legacy")
    assert legacy.outcome == "unmatched"
    assert legacy.delivery_id is None
    assert (
        db_session.get(PurchaseEmailDelivery, delivery_id).provider_message_id is None
    )
    db_session.rollback()
    monkeypatch.setattr(
        "app.services.purchase_email_delivery_service._build_transactional_email",
        lambda *args, **kwargs: None,
    )

    class Transport:
        def send(self, message):
            return EmailTransportResult("provider-email")

    assert (
        attempt_purchase_email_delivery(
            db_session, sale_id=sale_id, transport=Transport()
        )
        == "sent"
    )
    delivery = db_session.get(PurchaseEmailDelivery, delivery_id)
    assert delivery.provider_message_id == "provider-email"
    assert delivery.provider_delivery_status == "bounced"
    assert db_session.get(ResendWebhookEvent, "msg_legacy").outcome == "applied"
    assert db_session.get(ResendWebhookEvent, "msg_legacy").delivery_id == delivery_id
    assert db_session.get(ResendWebhookEvent, "msg_other").outcome == "unmatched"
    assert db_session.get(ResendWebhookEvent, "msg_other_tag").outcome == "unmatched"
    incident = db_session.query(PurchaseDeliveryIncident).one()
    assert incident.originating_event_id == "msg_legacy"


def test_authenticated_replay_reprocesses_same_unmatched_receipt_once(
    client, db_session
):
    delivery_id, _ = make_delivery(db_session, provider_id=None)
    body = event("email.bounced")
    assert send(client, "msg_legacy", body).status_code == 204
    receipt = db_session.get(ResendWebhookEvent, "msg_legacy")
    received_at = receipt.first_received_at
    assert receipt.outcome == "unmatched"
    # Simulate a receipt that committed after send completion checked its batch.
    delivery = db_session.get(PurchaseEmailDelivery, delivery_id)
    delivery.provider_message_id = "provider-email"
    db_session.commit()

    changed = event("email.failed", delivery_id=delivery_id)
    assert send(client, "msg_legacy", changed).status_code == 204
    db_session.refresh(receipt)
    assert receipt.outcome == "unmatched"
    db_session.rollback()

    assert send(client, "msg_legacy", body).status_code == 204
    db_session.refresh(receipt)
    assert receipt.outcome == "applied"
    assert receipt.first_received_at == received_at
    assert receipt.delivery_id == delivery_id
    incident = db_session.query(PurchaseDeliveryIncident).one()
    incident_id = incident.id
    db_session.rollback()
    assert resolve_operator_incident(
        db_session,
        incident_id=incident_id,
        operator="ops",
        reason="Reviewed",
        confirmed=True,
    )

    for svix_id in ("msg_legacy", "msg_manual_replay"):
        assert send(client, svix_id, body).status_code == 204
    assert db_session.query(PurchaseDeliveryIncident).count() == 1
    assert db_session.get(PurchaseDeliveryIncident, incident_id).resolved_at is not None
    assert (
        db_session.get(ResendWebhookEvent, "msg_manual_replay").outcome
        == "duplicate_event"
    )


def test_contradictory_tag_cannot_update_another_delivery(client, db_session):
    first, _ = make_delivery(db_session, "provider-email")
    second, _ = make_delivery(db_session, "other-email")
    body = event("email.complained", delivery_id=second)
    assert send(client, "msg_conflict", body).status_code == 204
    assert send(client, "msg_conflict_replay", body).status_code == 204
    assert (
        db_session.get(ResendWebhookEvent, "msg_conflict").outcome
        == "correlation_conflict"
    )
    assert (
        db_session.get(ResendWebhookEvent, "msg_conflict_replay").outcome
        == "duplicate_event"
    )
    assert db_session.query(PurchaseDeliveryIncident).count() == 1
    for delivery_id in (first, second):
        delivery = db_session.get(PurchaseEmailDelivery, delivery_id)
        assert delivery.provider_event_id is None
        assert delivery.complaint_event_id is None


def test_warning_resolution_and_operator_resolution_cli(
    client, db_session, monkeypatch
):
    delivery_id, _ = make_delivery(db_session)
    assert (
        send(
            client,
            "msg_delayed",
            event("email.delivery_delayed", delivery_id=delivery_id),
        ).status_code
        == 204
    )
    assert scan_purchase_delivery(db_session)["by_kind"]["email_provider_delayed"] == 1
    at = EVENT_TIME + timedelta(minutes=1)
    bounce = event("email.bounced", delivery_id=delivery_id, at=at)
    assert send(client, "msg_bounce", bounce).status_code == 204
    summary = scan_purchase_delivery(db_session)
    assert "email_provider_delayed" not in summary["by_kind"]
    assert summary["by_kind"]["email_provider_bounced"] == 1
    incidents = db_session.scalars(select(PurchaseDeliveryIncident)).all()
    warning = next(
        incident for incident in incidents if incident.kind == "email_provider_delayed"
    )
    terminal = next(
        incident for incident in incidents if incident.kind == "email_provider_bounced"
    )
    warning_id, terminal_id = warning.id, terminal.id
    assert warning.resolved_at is not None
    assert warning.originating_event_id == "msg_delayed"
    assert terminal.resolved_at is None
    db_session.rollback()

    monkeypatch.setattr("app.core.db.SessionLocal", lambda: db_session)
    args = ["--operator", "ops", "--reason", "Reviewed provider delivery"]
    assert resolve_main(["--incident-id", str(terminal_id), *args]) == 1
    assert resolve_main(["--incident-id", str(warning_id), "--confirm", *args]) == 1
    assert resolve_main(["--incident-id", str(terminal_id), "--confirm", *args]) == 0
    assert resolve_main(["--incident-id", str(terminal_id), "--confirm", *args]) == 1
    for svix_id in ("msg_bounce", "msg_bounce_replay"):
        assert send(client, svix_id, bounce).status_code == 204
    assert "email_provider_bounced" not in scan_purchase_delivery(db_session)["by_kind"]
    terminal = db_session.get(PurchaseDeliveryIncident, terminal_id)
    assert terminal.resolved_at is not None
    assert terminal.resolved_by == "ops"
    assert terminal.resolution_reason == "Reviewed provider delivery"
    assert (
        db_session.get(PurchaseEmailDelivery, delivery_id).provider_delivery_status
        == "bounced"
    )


def test_confirmation_timeout_and_retention_boundary(client, db_session):
    delivery_id, _ = make_delivery(db_session, provider_id=None)
    assert (
        send(
            client, "msg_pending", event("email.failed", delivery_id=delivery_id)
        ).status_code
        == 204
    )
    receipt = db_session.get(ResendWebhookEvent, "msg_pending")
    received_at = receipt.first_received_at.replace(tzinfo=UTC)
    db_session.rollback()
    timeout_at = received_at + timedelta(minutes=5)
    assert (
        "email_provider_confirmation_overdue"
        not in scan_purchase_delivery(
            db_session, now=timeout_at - timedelta(microseconds=1)
        )["by_kind"]
    )
    assert (
        scan_purchase_delivery(db_session, now=timeout_at)["by_kind"][
            "email_provider_confirmation_overdue"
        ]
        == 1
    )
    assert scan_purchase_delivery(db_session, now=timeout_at)["opened"] == 0
    expires_at = received_at + timedelta(days=90)
    scan_purchase_delivery(db_session, now=expires_at - timedelta(microseconds=1))
    assert db_session.get(ResendWebhookEvent, "msg_pending") is not None
    db_session.rollback()
    assert (
        scan_purchase_delivery(db_session, now=expires_at)["by_kind"][
            "email_provider_confirmation_overdue"
        ]
        == 1
    )
    assert db_session.get(ResendWebhookEvent, "msg_pending") is None
    assert (
        db_session.get(PurchaseEmailDelivery, delivery_id).provider_message_id is None
    )


def test_database_failure_rolls_back_and_returns_503(client, db_session, monkeypatch):
    from app.services.webhooks.resend_webhook_service import process_resend_webhook

    delivery_id, _ = make_delivery(db_session)

    def fail_after_receipt(db, **kwargs):
        process_resend_webhook(db, **kwargs)
        raise SQLAlchemyError("private provider data")

    monkeypatch.setattr(
        "app.api.v1.webhooks.process_resend_webhook", fail_after_receipt
    )
    response = send(
        client, "msg_rollback", event("email.delivered", delivery_id=delivery_id)
    )
    assert response.status_code == 503
    assert "private provider data" not in response.text
    assert db_session.get(ResendWebhookEvent, "msg_rollback") is None
    assert db_session.get(PurchaseEmailDelivery, delivery_id).provider_event_id is None
