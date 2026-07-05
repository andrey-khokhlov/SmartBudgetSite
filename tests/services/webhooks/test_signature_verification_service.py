import hashlib
import hmac

from app.core.config import settings

from app.services.webhooks.signature_verification_service import (
    verify_webhook_signature,
)


def test_verify_webhook_signature_rejects_unsupported_provider():
    """
    Test case: unsupported webhook provider

    What we verify:
    - Unknown providers are rejected safely.

    Business rule:
    - Unsupported webhook providers must not enter processing pipeline.
    """

    result = verify_webhook_signature(
        provider="unknown",
        payload=b"{}",
        headers={},
    )

    assert result is False


def test_verify_webhook_signature_accepts_valid_calendly_hmac_signature(monkeypatch):
    """
    Test case: valid Calendly HMAC webhook signature.

    What we verify:
    - Calendly webhook signature is accepted when HMAC matches.

    Business rule:
    - Only webhooks signed with our Calendly signing secret
      may enter lifecycle synchronization pipeline.
    """

    payload = b'{"event":"invitee.created"}'
    signing_secret = "test-secret"
    timestamp = "1492774577"

    signed_payload = f"{timestamp}.".encode("utf-8") + payload

    signature = hmac.new(
        signing_secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    monkeypatch.setattr(
        settings,
        "CALENDLY_WEBHOOK_SIGNING_SECRET",
        signing_secret,
    )

    result = verify_webhook_signature(
        provider="calendly",
        payload=payload,
        headers={
            "Calendly-Webhook-Signature": f"t={timestamp},v1={signature}",
            "Calendly-Webhook-Signing-Secret": signing_secret,
        },
    )

    assert result is True


def test_verify_webhook_signature_rejects_invalid_calendly_hmac_signature():
    """
    Test case: invalid Calendly HMAC webhook signature.

    What we verify:
    - Invalid webhook signature is rejected.

    Business rule:
    - Webhook authenticity must be verified cryptographically.
    """

    payload = b'{"event":"invitee.created"}'

    result = verify_webhook_signature(
        provider="calendly",
        payload=payload,
        headers={
            "Calendly-Webhook-Signature": (
                "t=1492774577,v1=INVALID_SIGNATURE"
            ),
            "Calendly-Webhook-Signing-Secret": "test-secret",
        },
    )

    assert result is False
