from app.services.webhooks.signature_verification_service import (
    verify_webhook_signature,
)


def test_verify_webhook_signature_rejects_missing_calendly_signature_header():
    """
    Test case: missing Calendly webhook signature header.

    What we verify:
    - Calendly verification rejects requests without signature header.

    Business rule:
    - Unsigned webhook requests must never enter
      lifecycle synchronization pipeline.
    """

    result = verify_webhook_signature(
        provider="calendly",
        payload=b'{"test": "payload"}',
        headers={},
    )

    assert result is False


def test_verify_webhook_signature_rejects_unknown_provider():
    """
    Test case: unsupported webhook provider.

    What we verify:
    - Unsupported providers are rejected safely.

    Business rule:
    - Webhook verification must fail closed for unknown providers.
    """

    result = verify_webhook_signature(
        provider="unknown-provider",
        payload=b'{}',
        headers={},
    )

    assert result is False
