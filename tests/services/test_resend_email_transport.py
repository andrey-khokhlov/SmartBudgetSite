from app.core.config import settings
from app.services.email_transport import TransactionalEmail
from app.services.resend_email_transport import ResendEmailTransport


class FakeResponse:
    status_code = 200

    def json(self):
        return {"id": "resend-id-123"}


def test_resend_uses_configured_sender_and_stable_idempotency_key(monkeypatch):
    captured = {}
    monkeypatch.setattr(settings, "RESEND_API_KEY", "private-api-key")

    def fake_post(url, *, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return FakeResponse()

    monkeypatch.setattr("app.services.resend_email_transport.httpx.post", fake_post)
    result = ResendEmailTransport().send(
        TransactionalEmail(
            recipient="buyer@example.test",
            sender_email="support@example.test",
            sender_name="SmartBudget",
            subject="Purchase",
            text_body="protected link",
            html_body="<p>protected link</p>",
            idempotency_key="purchase-email/42",
        )
    )

    assert result.provider_message_id == "resend-id-123"
    assert captured["headers"]["Idempotency-Key"] == "purchase-email/42"
    assert captured["json"]["from"] == "SmartBudget <support@example.test>"
    assert captured["headers"]["Authorization"] == "Bearer private-api-key"
