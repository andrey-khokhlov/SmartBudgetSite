import io
import logging
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from app.core.logging import StructuredWebhookFormatter
from app.services.webhooks.calendly_webhook_service import process_calendly_webhook


def _get_operational_console_handler() -> logging.StreamHandler:
    return next(
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler, logging.StreamHandler)
        and isinstance(handler.formatter, StructuredWebhookFormatter)
    )


@contextmanager
def _capture_handler_output(handler: logging.StreamHandler):
    original_stream = handler.stream
    output = io.StringIO()
    handler.setStream(output)

    try:
        yield output
    finally:
        handler.flush()
        handler.setStream(original_stream)


@pytest.fixture()
def operational_log_output():
    with _capture_handler_output(_get_operational_console_handler()) as output:
        yield output


def test_rejected_webhook_audit_fields_reach_operational_output(
    client,
    operational_log_output,
):
    with patch(
        "app.api.v1.webhooks.verify_webhook_signature",
        return_value=False,
    ):
        response = client.post(
            "/v1/webhooks/calendly",
            json={"event": "invitee.created", "payload": {}},
        )

    output = operational_log_output.getvalue()

    assert response.status_code == 401
    assert "Webhook event processed" in output
    assert "provider='calendly'" in output
    assert "event_type='signature_verification'" in output
    assert "status='rejected'" in output


def test_ignored_webhook_audit_fields_reach_operational_output(
    db_session,
    operational_log_output,
):
    result = process_calendly_webhook(
        db=db_session,
        payload={
            "event": "invitee.canceled\r\nforged\x00\tПривет",
            "payload": {},
        },
    )

    output = operational_log_output.getvalue()

    assert result is None
    assert "Webhook event processed" in output
    assert "provider='calendly'" in output
    assert (
        "event_type='invitee.canceled\\r\\nforged\\x00\\tПривет'" in output
    )
    assert "status='ignored'" in output
    assert len(output.splitlines()) == 1


def test_ordinary_application_log_keeps_existing_output_contract():
    console_handler = _get_operational_console_handler()
    original_stream = console_handler.stream

    with _capture_handler_output(console_handler) as output_stream:
        logging.getLogger("smartbudget.test").info("Ordinary application event")

    output = output_stream.getvalue()

    assert console_handler.stream is original_stream
    assert "[smartbudget.test] Ordinary application event" in output
    assert "provider=" not in output
    assert "event_type=" not in output
    assert "status=" not in output
