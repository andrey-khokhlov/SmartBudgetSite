from decimal import Decimal

from app.models.enums import PaymentStatus
from app.models.refund_operation import RefundOperation
from app.models.sale import Sale


def add_paid_sale(db_session) -> Sale:
    sale = Sale(
        customer_email="admin-refund@example.com",
        amount=Decimal("50.00"),
        currency="RUB",
        payment_provider="lava_top",
        payment_status=PaymentStatus.PAID,
        external_payment_id="admin-refund-invoice",
    )
    db_session.add(sale)
    db_session.commit()
    return sale


def test_admin_refund_workflow_requires_authentication(client, db_session):
    sale = add_paid_sale(db_session)

    assert client.get(f"/admin/sales/{sale.id}").status_code == 403
    assert (
        client.post(
            f"/admin/sales/{sale.id}/refund/start",
            data={"confirmation": "start_full_refund"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/admin/sales/{sale.id}/refund/confirm",
            data={"acknowledgement": "verified_full_refund_in_lava_top"},
        ).status_code
        == 403
    )


def test_admin_requires_explicit_confirmation_for_both_actions(auth_client, db_session):
    sale = add_paid_sale(db_session)

    missing_start = auth_client.post(f"/admin/sales/{sale.id}/refund/start")
    wrong_start = auth_client.post(
        f"/admin/sales/{sale.id}/refund/start",
        data={"confirmation": "yes"},
    )

    assert missing_start.status_code == 422
    assert wrong_start.status_code == 400
    assert db_session.query(RefundOperation).count() == 0

    started = auth_client.post(
        f"/admin/sales/{sale.id}/refund/start",
        data={"confirmation": "start_full_refund"},
        follow_redirects=False,
    )
    missing_confirm = auth_client.post(f"/admin/sales/{sale.id}/refund/confirm")
    wrong_confirm = auth_client.post(
        f"/admin/sales/{sale.id}/refund/confirm",
        data={"acknowledgement": "sent"},
    )

    assert started.status_code == 303
    assert missing_confirm.status_code == 422
    assert wrong_confirm.status_code == 400
    db_session.expire_all()
    assert db_session.get(Sale, sale.id).payment_status == PaymentStatus.PAID


def test_admin_full_refund_flow_is_visible_and_confirmed(auth_client, db_session):
    sale = add_paid_sale(db_session)

    detail = auth_client.get(f"/admin/sales/{sale.id}")
    started = auth_client.post(
        f"/admin/sales/{sale.id}/refund/start",
        data={"confirmation": "start_full_refund"},
        follow_redirects=False,
    )
    pending_detail = auth_client.get(f"/admin/sales/{sale.id}")
    confirmed = auth_client.post(
        f"/admin/sales/{sale.id}/refund/confirm",
        data={"acknowledgement": "verified_full_refund_in_lava_top"},
        follow_redirects=False,
    )

    assert detail.status_code == 200
    assert "Start refund" in detail.text
    assert 'class="refund-confirmation-form"' in detail.text
    assert 'class="refund-confirmation-checkbox" required' in detail.text
    assert 'class="btn-primary refund-confirmation-button"' in detail.text
    assert "button.disabled = !checkbox.checked;" in detail.text
    assert 'checkbox.addEventListener("change", updateButtonState);' in detail.text
    assert started.status_code == 303
    assert (
        "Complete the exact full refund manually in Lava.top Sales"
        in pending_detail.text
    )
    assert "I verified the full refund in Lava.top." in pending_detail.text
    assert 'class="refund-confirmation-form"' in pending_detail.text
    assert 'class="refund-confirmation-checkbox" required' in pending_detail.text
    assert 'class="btn-primary refund-confirmation-button"' in pending_detail.text
    assert "button.disabled = !checkbox.checked;" in pending_detail.text
    assert confirmed.status_code == 303
    db_session.expire_all()
    assert db_session.get(Sale, sale.id).payment_status == PaymentStatus.REFUNDED
