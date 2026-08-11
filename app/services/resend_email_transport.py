import httpx

from app.core.config import settings
from app.services.email_transport import (
    EmailTransportAmbiguousError,
    EmailTransportDefinitiveError,
    EmailTransportResult,
    TransactionalEmail,
)

RESEND_EMAILS_URL = "https://api.resend.com/emails"


class ResendEmailTransport:
    """Resend REST adapter for provider-independent transactional email."""

    def send(self, email: TransactionalEmail) -> EmailTransportResult:
        api_key = (settings.RESEND_API_KEY or "").strip()
        if not api_key:
            raise EmailTransportDefinitiveError(
                "Transactional email transport is not configured."
            )

        try:
            response = httpx.post(
                RESEND_EMAILS_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Idempotency-Key": email.idempotency_key,
                },
                json={
                    "from": f"{email.sender_name} <{email.sender_email}>",
                    "to": [email.recipient],
                    "subject": email.subject,
                    "text": email.text_body,
                    "html": email.html_body,
                },
                timeout=httpx.Timeout(10.0, connect=5.0),
            )
        except httpx.HTTPError as exc:
            raise EmailTransportAmbiguousError(
                "Transactional email provider outcome is ambiguous."
            ) from exc

        if response.status_code >= 500 or response.status_code == 409:
            raise EmailTransportAmbiguousError(
                "Transactional email provider outcome is ambiguous."
            )
        if response.status_code >= 400:
            raise EmailTransportDefinitiveError(
                "Transactional email provider rejected the request."
            )

        try:
            payload = response.json()
            provider_message_id = payload["id"]
        except (ValueError, KeyError, TypeError) as exc:
            raise EmailTransportAmbiguousError(
                "Transactional email provider returned an ambiguous response."
            ) from exc

        if not isinstance(provider_message_id, str) or not provider_message_id.strip():
            raise EmailTransportAmbiguousError(
                "Transactional email provider returned an ambiguous response."
            )

        return EmailTransportResult(provider_message_id=provider_message_id)
