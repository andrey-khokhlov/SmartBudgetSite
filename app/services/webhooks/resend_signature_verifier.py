from collections.abc import Mapping

from svix.webhooks import Webhook, WebhookVerificationError


def verify_resend_signature(
    raw_body: bytes, headers: Mapping[str, str], secret: str
) -> bool:
    signed_headers = {
        name: headers.get(name, "")
        for name in ("svix-id", "svix-timestamp", "svix-signature")
    }
    if not all(signed_headers.values()):
        return False
    try:
        Webhook(secret).verify(raw_body, signed_headers)
    except (WebhookVerificationError, ValueError, OverflowError, OSError):
        return False
    return True
