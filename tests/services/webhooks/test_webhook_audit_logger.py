import hashlib
import logging

from app.services.webhooks.webhook_audit_logger import log_webhook_event


def test_payment_audit_preserves_hashed_invoice_identity_without_raw_data(
    caplog,
):
    invoice_id = "provider-invoice-private-123"
    with caplog.at_level(logging.INFO):
        log_webhook_event(
            provider="lava_top",
            event_type="payment.success",
            status="processed",
            external_payment_id=invoice_id,
            sale_id=42,
        )

    record = caplog.records[-1]
    assert (
        record.external_payment_id_hash
        == hashlib.sha256(invoice_id.encode("utf-8")).hexdigest()
    )
    assert record.sale_id == 42
    assert invoice_id not in record.getMessage()
    assert "buyer@example.com" not in record.getMessage()
