from decimal import Decimal

import httpx
import pytest

from app.core.config import settings
from app.services.lava_top.client import (
    LavaTopConfigurationError,
    LavaTopInvoiceStatus,
    LavaTopRequestError,
    create_invoice,
    get_invoice,
)


def test_create_invoice_sends_sale_snapshot_and_parses_response(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return httpx.Response(
            200,
            json={
                "id": "invoice-123",
                "status": "new",
                "amountTotal": 50,
                "paymentUrl": "https://pay.example/hosted?token=secret",
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(settings, "LAVA_TOP_API_KEY", "server-api-key")
    monkeypatch.setattr(settings, "LAVA_TOP_API_BASE_URL", "https://gate.lava.top/")
    monkeypatch.setattr(httpx, "post", fake_post)

    invoice = create_invoice(
        email="buyer@example.com",
        offer_id="offer-from-database",
        currency="RUB",
        amount=Decimal("50.00"),
    )

    assert captured["url"] == "https://gate.lava.top/api/v3/invoice"
    assert captured["headers"] == {"X-Api-Key": "server-api-key"}
    assert captured["json"] == {
        "email": "buyer@example.com",
        "offerId": "offer-from-database",
        "currency": "RUB",
        "amount": 50.0,
    }
    assert isinstance(captured["timeout"], httpx.Timeout)
    assert invoice.invoice_id == "invoice-123"
    assert invoice.payment_url == "https://pay.example/hosted?token=secret"


def test_create_invoice_fails_closed_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "LAVA_TOP_API_KEY", "")

    with pytest.raises(LavaTopConfigurationError):
        create_invoice(
            email="buyer@example.com",
            offer_id="offer-from-database",
            currency="EUR",
            amount=Decimal("39.00"),
        )


def test_create_invoice_converts_network_error(monkeypatch):
    def fail_post(url, **kwargs):
        request = httpx.Request("POST", url)
        raise httpx.ConnectError("provider unavailable", request=request)

    monkeypatch.setattr(settings, "LAVA_TOP_API_KEY", "server-api-key")
    monkeypatch.setattr(httpx, "post", fail_post)

    with pytest.raises(LavaTopRequestError):
        create_invoice(
            email="buyer@example.com",
            offer_id="offer-from-database",
            currency="EUR",
            amount=Decimal("39.00"),
        )


def test_create_invoice_converts_non_success_response(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            503,
            json={"message": "unavailable"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(settings, "LAVA_TOP_API_KEY", "server-api-key")
    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(LavaTopRequestError):
        create_invoice(
            email="buyer@example.com",
            offer_id="offer-from-database",
            currency="EUR",
            amount=Decimal("39.00"),
        )


def test_get_invoice_uses_exact_identity_and_parses_receipt(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return httpx.Response(
            200,
            json={
                "id": "invoice-123",
                "status": "COMPLETED",
                "receipt": {"amount": 50, "currency": "RUB", "fee": 1},
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(settings, "LAVA_TOP_API_KEY", "outbound-api-key")
    monkeypatch.setattr(settings, "LAVA_TOP_API_BASE_URL", "https://gate.lava.top/")
    monkeypatch.setattr(httpx, "get", fake_get)

    invoice = get_invoice("invoice-123")

    assert captured["url"] == "https://gate.lava.top/api/v2/invoices/invoice-123"
    assert captured["headers"] == {"X-Api-Key": "outbound-api-key"}
    assert invoice.status == LavaTopInvoiceStatus.COMPLETED
    assert invoice.amount == Decimal("50")
    assert invoice.currency == "RUB"


def test_get_invoice_rejects_changed_provider_identity(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(
            200,
            json={"id": "different", "status": "FAILED"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(settings, "LAVA_TOP_API_KEY", "outbound-api-key")
    monkeypatch.setattr(httpx, "get", fake_get)

    from app.services.lava_top.client import LavaTopResponseError

    with pytest.raises(LavaTopResponseError):
        get_invoice("invoice-123")
