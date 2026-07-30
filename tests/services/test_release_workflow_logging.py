import logging

from app.core.logging import StructuredWebhookFormatter


def test_release_workflow_formatter_preserves_only_approved_fields() -> None:
    formatter = StructuredWebhookFormatter("%(levelname)s %(message)s")
    record = logging.LogRecord(
        name="app.services.product_release_service",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Product release workflow event",
        args=(),
        exc_info=None,
    )
    record.operation_id = "operation-reference"
    record.product_id = 42
    record.workflow_phase = "verification"
    record.storage_provider = "cloudflare_r2"
    record.outcome = "compensated"
    record.storage_key_digest = "a" * 64

    output = formatter.format(record)

    assert "operation_id='operation-reference'" in output
    assert "product_id='42'" in output
    assert "workflow_phase='verification'" in output
    assert "storage_provider='cloudflare_r2'" in output
    assert "outcome='compensated'" in output
    assert f"storage_key_digest='{'a' * 64}'" in output
