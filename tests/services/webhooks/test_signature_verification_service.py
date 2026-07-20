import hashlib
import hmac
import time

import pytest

from app.core.config import settings
from app.services.webhooks.signature_verification_service import (
    CALENDLY_SIGNATURE_TOLERANCE_SECONDS,
    _is_timestamp_within_tolerance,
    _verify_calendly_signature,
    verify_webhook_signature,
)


PAYLOAD = b'{"event":"invitee.created"}'
SIGNING_SECRET = "test-secret"
CURRENT_TIMESTAMP = 1_700_000_000


def _build_signature(timestamp: str) -> str:
    signed_payload = f"{timestamp}.".encode("utf-8") + PAYLOAD
    return hmac.new(
        SIGNING_SECRET.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()


def _build_headers(timestamp: str) -> dict[str, str]:
    return {
        "Calendly-Webhook-Signature": (
            f"t={timestamp},v1={_build_signature(timestamp)}"
        )
    }


def test_verify_webhook_signature_rejects_unsupported_provider():
    result = verify_webhook_signature(
        provider="unknown",
        payload=b"{}",
        headers={},
    )

    assert result is False


def test_verify_webhook_signature_accepts_valid_current_calendly_signature(
    monkeypatch,
):
    current_timestamp = int(time.time())
    timestamp = str(current_timestamp)
    monkeypatch.setattr(
        settings,
        "CALENDLY_WEBHOOK_SIGNING_SECRET",
        SIGNING_SECRET,
    )

    result = verify_webhook_signature(
        provider="calendly",
        payload=PAYLOAD,
        headers=_build_headers(timestamp),
    )

    assert result is True


@pytest.mark.parametrize(
    ("offset_seconds", "expected"),
    [
        (-CALENDLY_SIGNATURE_TOLERANCE_SECONDS, True),
        (CALENDLY_SIGNATURE_TOLERANCE_SECONDS, True),
        (-CALENDLY_SIGNATURE_TOLERANCE_SECONDS - 1, False),
        (CALENDLY_SIGNATURE_TOLERANCE_SECONDS + 1, False),
    ],
    ids=["old-boundary", "future-boundary", "too-old", "too-far-future"],
)
def test_calendly_signature_enforces_inclusive_timestamp_tolerance(
    monkeypatch,
    offset_seconds,
    expected,
):
    signed_timestamp = CURRENT_TIMESTAMP + offset_seconds
    monkeypatch.setattr(
        settings,
        "CALENDLY_WEBHOOK_SIGNING_SECRET",
        SIGNING_SECRET,
    )

    assert (
        _is_timestamp_within_tolerance(
            signed_timestamp=signed_timestamp,
            current_timestamp=CURRENT_TIMESTAMP,
        )
        is expected
    )
    assert (
        _verify_calendly_signature(
            payload=PAYLOAD,
            headers=_build_headers(str(signed_timestamp)),
            current_timestamp=CURRENT_TIMESTAMP,
        )
        is expected
    )


@pytest.mark.parametrize(
    "signature_header",
    [
        f"v1={'a' * 64}",
        f"t=,v1={'a' * 64}",
        f"t={CURRENT_TIMESTAMP}",
        f"t={CURRENT_TIMESTAMP},v1=",
        f"t=not-a-number,v1={'a' * 64}",
        f"t={CURRENT_TIMESTAMP}.5,v1={'a' * 64}",
        f"t=-{CURRENT_TIMESTAMP},v1={'a' * 64}",
        f"t={CURRENT_TIMESTAMP},t={CURRENT_TIMESTAMP},v1={'a' * 64}",
        f"t={CURRENT_TIMESTAMP},v1={'a' * 64},v1={'b' * 64}",
        f"t={CURRENT_TIMESTAMP},malformed,v1={'a' * 64}",
        f"t={CURRENT_TIMESTAMP},v1={'g' * 64}",
        f"t={CURRENT_TIMESTAMP},v1=é",
    ],
    ids=[
        "missing-timestamp",
        "empty-timestamp",
        "missing-signature",
        "empty-signature",
        "non-numeric-timestamp",
        "fractional-timestamp",
        "negative-timestamp",
        "duplicate-timestamp",
        "duplicate-signature",
        "malformed-fragment",
        "invalid-digest",
        "non-ascii-digest",
    ],
)
def test_verify_calendly_signature_rejects_malformed_header(
    monkeypatch,
    signature_header,
):
    monkeypatch.setattr(
        settings,
        "CALENDLY_WEBHOOK_SIGNING_SECRET",
        SIGNING_SECRET,
    )

    result = _verify_calendly_signature(
        payload=PAYLOAD,
        headers={"Calendly-Webhook-Signature": signature_header},
        current_timestamp=CURRENT_TIMESTAMP,
    )

    assert result is False


def test_verify_calendly_signature_rejects_millisecond_timestamp(monkeypatch):
    millisecond_timestamp = str(CURRENT_TIMESTAMP * 1_000)
    monkeypatch.setattr(
        settings,
        "CALENDLY_WEBHOOK_SIGNING_SECRET",
        SIGNING_SECRET,
    )

    result = _verify_calendly_signature(
        payload=PAYLOAD,
        headers=_build_headers(millisecond_timestamp),
        current_timestamp=CURRENT_TIMESTAMP,
    )

    assert result is False


def test_verify_calendly_signature_rejects_invalid_hmac_within_tolerance(
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "CALENDLY_WEBHOOK_SIGNING_SECRET",
        SIGNING_SECRET,
    )

    result = _verify_calendly_signature(
        payload=PAYLOAD,
        headers={
            "Calendly-Webhook-Signature": (
                f"t={CURRENT_TIMESTAMP},v1={'0' * 64}"
            )
        },
        current_timestamp=CURRENT_TIMESTAMP,
    )

    assert result is False
