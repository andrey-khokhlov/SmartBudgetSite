import hashlib
import hmac
import string
import time
from collections.abc import Mapping

from app.core.config import settings


CALENDLY_SIGNATURE_HEADER = "Calendly-Webhook-Signature"
CALENDLY_SIGNING_SECRET_HEADER = "Calendly-Webhook-Signing-Secret"
CALENDLY_SIGNATURE_TOLERANCE_SECONDS = 180


def verify_webhook_signature(
    provider: str,
    payload: bytes,
    headers: Mapping[str, str],
) -> bool:
    """
    Verify webhook signature for external provider.
    """

    if provider == "calendly":
        current_timestamp = int(time.time())
        return _verify_calendly_signature(
            payload=payload,
            headers=headers,
            current_timestamp=current_timestamp,
        )

    return False


def _verify_calendly_signature(
    payload: bytes,
    headers: Mapping[str, str],
    current_timestamp: int,
) -> bool:
    signature_header = headers.get(CALENDLY_SIGNATURE_HEADER)
    signing_secret = settings.CALENDLY_WEBHOOK_SIGNING_SECRET

    if not signature_header or not signing_secret:
        return False

    try:
        timestamp, signed_timestamp, provided_signature = (
            _parse_calendly_signature_header(signature_header)
        )
    except ValueError:
        return False

    if not _is_timestamp_within_tolerance(
        signed_timestamp=signed_timestamp,
        current_timestamp=current_timestamp,
    ):
        return False

    signed_payload = f"{timestamp}.".encode("utf-8") + payload

    expected_signature = hmac.new(
        signing_secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_signature, provided_signature)


def _parse_calendly_signature_header(
    signature_header: str,
) -> tuple[str, int, str]:
    parts: dict[str, str] = {}

    for fragment in signature_header.split(","):
        if "=" not in fragment:
            raise ValueError("Invalid Calendly signature header.")

        key, value = fragment.split("=", maxsplit=1)
        if key not in {"t", "v1"} or not value or key in parts:
            raise ValueError("Invalid Calendly signature header.")

        parts[key] = value

    timestamp = parts.get("t")
    signature = parts.get("v1")

    if not timestamp or not signature:
        raise ValueError("Invalid Calendly signature header.")

    if not timestamp.isascii() or not timestamp.isdecimal():
        raise ValueError("Invalid Calendly signature header.")

    if len(signature) != hashlib.sha256().digest_size * 2 or any(
        character not in string.hexdigits for character in signature
    ):
        raise ValueError("Invalid Calendly signature header.")

    return timestamp, int(timestamp), signature


def _is_timestamp_within_tolerance(
    signed_timestamp: int,
    current_timestamp: int,
    tolerance_seconds: int = CALENDLY_SIGNATURE_TOLERANCE_SECONDS,
) -> bool:
    return abs(current_timestamp - signed_timestamp) <= tolerance_seconds
