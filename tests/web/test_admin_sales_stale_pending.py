from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models.enums import PaymentCheckResult, PaymentStatus
from app.models.sale import Sale


def add_sale(
    db_session,
    *,
    status,
    age,
    external_payment_id=None,
    payment_last_checked_at=None,
    payment_last_check_result=None,
):
    sale = Sale(
        customer_email="operator-test@example.com",
        amount=Decimal("50.00"),
        currency="RUB",
        payment_provider="lava_top",
        payment_status=status,
        external_payment_id=(
            external_payment_id
            if external_payment_id is not None
            else f"admin-{status}-{age.total_seconds()}"
        ),
        payment_last_checked_at=payment_last_checked_at,
        payment_last_check_result=payment_last_check_result,
        created_at=datetime.now(UTC) - age,
    )
    db_session.add(sale)
    db_session.commit()
    return sale


def test_admin_marks_only_unchecked_old_pending_sale_as_needing_check(
    auth_client,
    db_session,
):
    stale = add_sale(
        db_session,
        status=PaymentStatus.PENDING,
        age=timedelta(hours=25),
    )
    current = add_sale(
        db_session,
        status=PaymentStatus.PENDING,
        age=timedelta(hours=1),
    )
    paid = add_sale(
        db_session,
        status=PaymentStatus.PAID,
        age=timedelta(days=2),
    )
    failed = add_sale(
        db_session,
        status=PaymentStatus.FAILED,
        age=timedelta(hours=1),
    )
    refunded = add_sale(
        db_session,
        status=PaymentStatus.REFUNDED,
        age=timedelta(hours=1),
    )

    response = auth_client.get("/admin/sales")

    assert response.status_code == 200
    stale_row = response.text.split(f">{stale.id}<", 1)[1].split("</tr>", 1)[0]
    current_row = response.text.split(f">{current.id}<", 1)[1].split("</tr>", 1)[0]
    paid_row = response.text.split(f">{paid.id}<", 1)[1].split("</tr>", 1)[0]
    failed_row = response.text.split(f">{failed.id}<", 1)[1].split("</tr>", 1)[0]
    refunded_row = response.text.split(f">{refunded.id}<", 1)[1].split("</tr>", 1)[0]
    assert "Check needed" in stale_row
    assert "Check needed" not in current_row
    assert "Check needed" not in paid_row
    for sale, row in (
        (stale, stale_row),
        (current, current_row),
        (paid, paid_row),
        (failed, failed_row),
        (refunded, refunded_row),
    ):
        assert f'href="/admin/sales/{sale.id}"' in row
        assert "Details" in row
        assert "/refund/start" not in row
    assert "Start refund" not in response.text
    assert "Pending &gt;24h — check" not in response.text


def test_admin_marks_checked_stale_pending_sale_as_waiting(auth_client, db_session):
    checked_at = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    sale = add_sale(
        db_session,
        status=PaymentStatus.PENDING,
        age=timedelta(hours=25),
        payment_last_checked_at=checked_at,
        payment_last_check_result=PaymentCheckResult.NON_TERMINAL.value,
    )

    response = auth_client.get("/admin/sales")

    assert response.status_code == 200
    sale_row = response.text.split(f">{sale.id}<", 1)[1].split("</tr>", 1)[0]
    assert "Checked — waiting" in sale_row
    assert "Check needed" not in sale_row
    assert 'title="Last checked: 2026-08-11T12:00:00"' in sale_row


def test_admin_external_id_copy_target_and_empty_state(auth_client, db_session):
    external_payment_id = "cc1137ac-f8dd-4d51-bd37-738431d6461d"
    with_external_id = add_sale(
        db_session,
        status=PaymentStatus.PAID,
        age=timedelta(hours=1),
        external_payment_id=external_payment_id,
    )
    without_external_id = add_sale(
        db_session,
        status=PaymentStatus.PENDING,
        age=timedelta(hours=1),
        external_payment_id="",
    )
    without_external_id.external_payment_id = None
    db_session.commit()

    response = auth_client.get("/admin/sales")

    assert response.status_code == 200
    configured_row = response.text.split(f">{with_external_id.id}<", 1)[1].split(
        "</tr>", 1
    )[0]
    empty_row = response.text.split(f">{without_external_id.id}<", 1)[1].split(
        "</tr>", 1
    )[0]
    assert 'class="sales-external-id"' in configured_row
    assert f'data-external-payment-id="{external_payment_id}"' in configured_row
    assert "Click to copy full External ID" in configured_row
    assert external_payment_id in configured_row
    assert 'class="sales-external-id"' not in empty_row
    assert "data-external-payment-id" not in empty_row
    external_cell = empty_row.split('<td class="sales-col-external">', 1)[1].split(
        "</td>", 1
    )[0]
    assert external_cell.strip() == "-"
