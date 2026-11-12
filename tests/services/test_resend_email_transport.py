import httpx
import pytest

from app.core.config import settings
from app.services.email_transport import (
    EmailTransportAmbiguousError,
    EmailTransportDefinitiveError,
    EmailTransportIdempotencyConflictError,
    EmailTransportPermanentError,
    EmailTransportTransientError,
    TransactionalEmail,
)
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
            purchase_email_delivery_id=42,
        )
    )

    assert result.provider_message_id == "resend-id-123"
    assert captured["headers"]["Idempotency-Key"] == "purchase-email/42"
    assert captured["json"]["from"] == "SmartBudget <support@example.test>"
    assert captured["json"]["tags"] == [
        {"name": "purchase_email_delivery_id", "value": "42"}
    ]
    assert captured["headers"]["Authorization"] == "Bearer private-api-key"


@pytest.mark.parametrize(
    ("status", "name", "expected"),
    [
        (429, "rate_limit_exceeded", EmailTransportTransientError),
        (429, "daily_quota_exceeded", EmailTransportDefinitiveError),
        (429, "monthly_quota_exceeded", EmailTransportDefinitiveError),
        (429, "unknown", EmailTransportDefinitiveError),
        (422, "validation_error", EmailTransportPermanentError),
        (401, "missing_api_key", EmailTransportPermanentError),
        (503, "service_unavailable", EmailTransportAmbiguousError),
    ],
)
def test_resend_classifies_only_explicit_transient_rejection(
    monkeypatch, status, name, expected
):
    monkeypatch.setattr(settings, "RESEND_API_KEY", "private-api-key")
    monkeypatch.setattr(
        "app.services.resend_email_transport.httpx.post",
        lambda *args, **kwargs: httpx.Response(status, json={"name": name}),
    )
    with pytest.raises(expected) as error:
        ResendEmailTransport().send(
            TransactionalEmail(
                recipient="buyer@example.test",
                sender_email="support@example.test",
                sender_name="SmartBudget",
                subject="Purchase",
                text_body="protected",
                html_body="<p>protected</p>",
                idempotency_key="purchase-email/42",
            )
        )
    assert type(error.value) is expected


@pytest.mark.parametrize(
    ("content", "exception_type"),
    [
        (
            b'{"name":"invalid_idempotent_request","message":"private@example.test private-token"}',
            EmailTransportIdempotencyConflictError,
        ),
        (b'{"name":"concurrent_idempotent_requests"}', EmailTransportAmbiguousError),
        (b'{"name":"unknown"}', EmailTransportAmbiguousError),
        (b'{"message":"invalid_idempotent_request"}', EmailTransportAmbiguousError),
        (b'["invalid_idempotent_request"]', EmailTransportAmbiguousError),
        (b"malformed invalid_idempotent_request", EmailTransportAmbiguousError),
    ],
)
def test_resend_409_classification(monkeypatch, caplog, content, exception_type):
    monkeypatch.setattr(settings, "RESEND_API_KEY", "private-api-key")
    monkeypatch.setattr(
        "app.services.resend_email_transport.httpx.post",
        lambda *args, **kwargs: httpx.Response(409, content=content),
    )

    with pytest.raises(exception_type) as error:
        ResendEmailTransport().send(
            TransactionalEmail(
                recipient="private@example.test",
                sender_email="support@example.test",
                sender_name="SmartBudget",
                subject="Purchase",
                text_body="private-token",
                html_body="<p>private-token</p>",
                idempotency_key="purchase-email/42",
            )
        )

    assert type(error.value) is exception_type
    for secret in ("private@example.test", "private-token", "private-api-key"):
        assert secret not in str(error.value)
        assert secret not in caplog.text
