from unittest.mock import Mock

import pytest

from app.core.config import settings
from app.models.purchase_access_recovery import PurchaseAccessRecovery
from app.models.sale import Sale
from app.services.email_transport import EmailTransportResult
from app.services.purchase_access_recovery_service import VERIFY_CONFIRMATION
from tests.services.test_purchase_access_recovery import create_paid_recovery_sale
from tests.services.test_purchase_email_delivery_service import configure_email


def form_csrf(page):
    return {
        "csrf_id": page.context["recovery_csrf_id"],
        "csrf_token": page.context["recovery_csrf_token"],
    }


def test_admin_recovery_actions_are_protected_and_do_not_expose_tokens(
    client, db_session, monkeypatch, caplog
):
    db = db_session
    sale_id = create_paid_recovery_sale(db, language="ru")
    old_token = db.get(Sale, sale_id).items[0].download_entitlement.download_token
    db.rollback()
    configure_email(monkeypatch)
    monkeypatch.setattr(settings, "SECRET_KEY", "test-recovery-csrf")
    monkeypatch.setattr(settings, "PURCHASE_EMAIL_DELIVERY_ENABLED", True)
    transport = Mock(return_value=EmailTransportResult("provider-message-123"))
    monkeypatch.setattr(
        "app.services.resend_email_transport.ResendEmailTransport.send", transport
    )
    path = f"/admin/sales/{sale_id}"
    prepare_path, send_path = (
        f"{path}/purchase-access/prepare",
        f"{path}/purchase-access/send",
    )
    details = {
        "verification_method": "provider_dashboard",
        "verification": VERIFY_CONFIRMATION,
        "reason": "Verified payment and requested correction.",
        "corrected_email": "corrected@example.com",
    }
    assert client.get(path).status_code == 403
    assert client.post(prepare_path, data=details).status_code == 403
    assert (
        client.post(
            send_path, data={"recovery_id": 1, "expected_attempt_count": 0}
        ).status_code
        == 403
    )
    client.cookies.set("admin_token", settings.ADMIN_TOKEN)
    assert client.post(prepare_path, data=details).status_code == 403
    assert (
        client.post(
            send_path, data={"recovery_id": 1, "expected_attempt_count": 0}
        ).status_code
        == 403
    )

    page = client.get(path)
    assert page.headers["Cache-Control"] == "no-store"
    assert "Prepare recovery" in page.text and "Send recovery email" not in page.text
    assert old_token not in page.text
    invalid = client.post(
        prepare_path, data=details | form_csrf(page) | {"verification": ""}
    )
    assert invalid.status_code == 400
    bad_csrf = client.post(
        prepare_path, data=details | form_csrf(page) | {"csrf_token": "f" * 64}
    )
    assert bad_csrf.status_code == 403

    data = details | form_csrf(page) | {"expected_recovery_id": 0}
    prepared = client.post(prepare_path, data=data, follow_redirects=False)
    replay = client.post(prepare_path, data=data, follow_redirects=False)
    assert prepared.status_code == replay.status_code == 303
    assert replay.headers["location"].endswith("recovery_result=already_prepared")
    transport.assert_not_called()
    row = db.query(PurchaseAccessRecovery).one()
    recovery_id = row.id
    new_token = db.get(Sale, sale_id).items[0].download_entitlement.download_token
    db.rollback()

    page = client.get(prepared.headers["location"])
    assert "Send recovery email" in page.text
    send_data = form_csrf(page) | {
        "recovery_id": recovery_id,
        "expected_attempt_count": 0,
    }
    sent = client.post(send_path, data=send_data, follow_redirects=False)
    assert sent.status_code == 303
    assert sent.headers["location"].endswith("recovery_result=accepted")
    assert (
        client.post(send_path, data=send_data, follow_redirects=False).status_code
        == 303
    )
    transport.assert_called_once()
    for value in (old_token, new_token):
        assert value not in page.text
        assert (
            value not in prepared.headers["location"]
            and value not in sent.headers["location"]
        )
        assert value not in caplog.text

    for endpoint, form in (
        ("retry", {}),
        ("authorize-resend", {"authorization": "provider_confirmed_not_sent"}),
    ):
        original = client.post(
            f"{path}/purchase-email/{endpoint}", data=form, follow_redirects=False
        )
        assert original.headers["location"].endswith("email_result=superseded")
    transport.assert_called_once()
    assert client.get(f"/download/{old_token}").status_code == 404
    assert client.post(f"/download/{old_token}").status_code == 404
    assert client.get(f"/download/{new_token}").status_code == 200


@pytest.mark.parametrize("kind", ["consultation", "bundle"])
def test_consultation_sales_show_manual_review(auth_client, db_session, kind):
    sale_id = create_paid_recovery_sale(db_session, kind=kind)
    page = auth_client.get(f"/admin/sales/{sale_id}")
    assert page.status_code == 200
    assert "Review consultation Sales manually." in page.text
    assert "Prepare recovery" not in page.text
    assert "Send recovery email" not in page.text
