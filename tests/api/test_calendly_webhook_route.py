import hashlib
import hmac
import json
import time
from unittest.mock import patch

from app.core.config import settings
from app.services.webhooks.signature_verification_service import (
    CALENDLY_SIGNATURE_TOLERANCE_SECONDS,
)


def _build_calendly_signature_header(
    payload: bytes,
    signing_secret: str,
    timestamp: str,
) -> str:
    signed_payload = f"{timestamp}.".encode("utf-8") + payload

    signature = hmac.new(
        signing_secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    return f"t={timestamp},v1={signature}"


def test_calendly_webhook_endpoint_accepts_post_request(client, monkeypatch):
    """
    Test case: Calendly webhook accepts valid signed request.

    What we verify:
    - The endpoint exists.
    - A valid Calendly HMAC signature is accepted.
    - Valid request returns 204 No Content.
    """

    payload = {
        "event": "invitee.created",
        "payload": {
            "event": "https://api.calendly.com/scheduled_events/ABC",
            "invitee": "https://api.calendly.com/invitees/XYZ",
        },
    }

    payload_bytes = json.dumps(payload).encode("utf-8")

    signing_secret = "test-secret"

    signature_header = _build_calendly_signature_header(
        payload=payload_bytes,
        signing_secret=signing_secret,
        timestamp=str(int(time.time())),
    )

    monkeypatch.setattr(
        settings,
        "CALENDLY_WEBHOOK_SIGNING_SECRET",
        signing_secret,
    )

    response = client.post(
        "/v1/webhooks/calendly",
        json=payload,
        headers={
            "Calendly-Webhook-Signature": signature_header,
        },
    )

    assert response.status_code == 204
    assert response.content == b""


def test_calendly_webhook_rejects_invalid_signature(client):
    """
    Test case: invalid Calendly webhook signature

    What we verify:
    - Invalid signature blocks request processing.
    - Webhook route returns 401.
    - Payload must not enter business processing when verification fails.

    Business rule:
    - Signature verification failure must stop webhook processing immediately.
    """

    with patch(
        "app.api.v1.webhooks.verify_webhook_signature",
        return_value=False,
    ):
        response = client.post(
            "/v1/webhooks/calendly",
            json={
                "event": "invitee.created",
                "payload": {
                    "event": {
                        "uri": "https://api.calendly.com/scheduled_events/ABC",
                    },
                    "invitee": {
                        "uri": "https://api.calendly.com/invitees/XYZ",
                    },
                },
            },
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid webhook signature"


def test_calendly_webhook_rejects_unsigned_request(client):
    """
    Test case: unsigned Calendly webhook request.

    What we verify:
    - Request is rejected before orchestration layer execution.

    Business rule:
    - Unverified webhook requests must never enter
      reconciliation or lifecycle synchronization pipeline.
    """

    with patch(
        "app.api.v1.webhooks.process_calendly_webhook"
    ) as mocked_process:

        response = client.post(
            "/v1/webhooks/calendly",
            json={"event": "invitee.created"},
        )

        assert response.status_code == 401

        mocked_process.assert_not_called()


def test_calendly_webhook_rejects_malformed_signature_header(
    client,
    monkeypatch,
):
    """
    Malformed Calendly signature headers must be rejected.

    This protects the webhook boundary from accepting headers that
    cannot be parsed into timestamp/signature components.
    """

    monkeypatch.setattr(
        settings,
        "CALENDLY_WEBHOOK_SIGNING_SECRET",
        "test-secret",
    )

    payload = {
        "event": "invitee.created",
        "payload": {
            "event": "https://api.calendly.com/scheduled_events/test-event",
            "invitee": "https://api.calendly.com/scheduled_events/test-event/invitees/test-invitee",
        },
    }

    response = client.post(
        "/v1/webhooks/calendly",
        json=payload,
        headers={
            "Calendly-Webhook-Signature": "not-a-valid-signature-header",
        },
    )

    assert response.status_code == 401


def test_calendly_webhook_logs_signature_rejection(
    client,
    monkeypatch,
):
    """
    Invalid webhook signatures must emit rejection audit logs.
    """

    monkeypatch.setattr(
        settings,
        "CALENDLY_WEBHOOK_SIGNING_SECRET",
        "test-secret",
    )

    payload = {
        "event": "invitee.created",
        "payload": {
            "event": "https://api.calendly.com/scheduled_events/test-event",
            "invitee": "https://api.calendly.com/invitees/test-invitee",
        },
    }

    with patch("app.api.v1.webhooks.log_webhook_event") as mocked_logger:
        response = client.post(
            "/v1/webhooks/calendly",
            json=payload,
            headers={
                "Calendly-Webhook-Signature": "malformed-header",
            },
        )

    assert response.status_code == 401

    mocked_logger.assert_called_once_with(
        provider="calendly",
        event_type="signature_verification",
        status="rejected",
    )


def test_calendly_webhook_rejects_correctly_signed_stale_request(
    client,
    monkeypatch,
):
    payload = {
        "event": "invitee.created",
        "payload": {
            "event": "https://api.calendly.com/scheduled_events/stale-event",
            "invitee": "https://api.calendly.com/invitees/stale-invitee",
        },
    }
    payload_bytes = json.dumps(payload).encode("utf-8")
    signing_secret = "test-secret"
    stale_timestamp = str(
        int(time.time()) - CALENDLY_SIGNATURE_TOLERANCE_SECONDS - 1
    )
    signature_header = _build_calendly_signature_header(
        payload=payload_bytes,
        signing_secret=signing_secret,
        timestamp=stale_timestamp,
    )
    monkeypatch.setattr(
        settings,
        "CALENDLY_WEBHOOK_SIGNING_SECRET",
        signing_secret,
    )

    with (
        patch("app.api.v1.webhooks.process_calendly_webhook") as mocked_process,
        patch("app.api.v1.webhooks.log_webhook_event") as mocked_logger,
    ):
        response = client.post(
            "/v1/webhooks/calendly",
            json=payload,
            headers={"Calendly-Webhook-Signature": signature_header},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid webhook signature"}
    mocked_process.assert_not_called()
    mocked_logger.assert_called_once_with(
        provider="calendly",
        event_type="signature_verification",
        status="rejected",
    )


def test_calendly_webhook_logs_malformed_json_rejection(
    client,
    monkeypatch,
):
    """
    Malformed JSON webhook payloads must be logged and rejected.

    This covers request-level parsing failures before the webhook
    orchestration service is reached.
    """

    monkeypatch.setattr(
        settings,
        "CALENDLY_WEBHOOK_SIGNING_SECRET",
        "test-secret",
    )

    raw_payload = b"{invalid-json"

    signature_header = _build_calendly_signature_header(
        payload=raw_payload,
        signing_secret="test-secret",
        timestamp=str(int(time.time())),
    )

    with patch("app.api.v1.webhooks.log_webhook_event") as mocked_logger:
        response = client.post(
            "/v1/webhooks/calendly",
            content=raw_payload,
            headers={
                "Content-Type": "application/json",
                "Calendly-Webhook-Signature": signature_header,
            },
        )

    assert response.status_code == 400

    mocked_logger.assert_called_once_with(
        provider="calendly",
        event_type="json_parse",
        status="malformed_payload",
    )
