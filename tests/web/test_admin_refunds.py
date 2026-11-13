from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm.attributes import set_committed_value

from app.models.enums import PaymentStatus, SaleItemType
from app.models.product import Product
from app.models.refund_operation import RefundOperation
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.service_addon import ServiceAddon
from app.web import routes


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


def add_sale_item(sale, item_type):
    item = SaleItem(
        item_type=item_type,
        item_name="Purchased item",
        currency_code=sale.currency,
        amount=sale.amount,
    )
    if item_type == SaleItemType.PRODUCT:
        item.product = Product(
            family_slug="smartbudget",
            slug="refund-window-product",
            name="SmartBudget",
            edition="Standard",
            archive_path="archives/refund.zip",
            status="in_sale",
        )
    else:
        item.service_addon = ServiceAddon(
            code="refund-window-consultation",
            name="Consultation",
            service_type="consultation",
            usage_type="standalone",
            family_slug="smartbudget",
            package_code="RU",
            currency_code=sale.currency,
            amount=sale.amount,
            is_active=True,
        )
    sale.items.append(item)


@pytest.fixture
def fixed_refund_review_clock(monkeypatch):
    load_sale = routes.get_refund_sale_for_admin
    assess_window = routes.assess_voluntary_refund_window

    def load_sale_with_aware_timestamp(db, sale_id):
        sale = load_sale(db, sale_id)
        if sale.paid_at is not None:
            # SQLite strips the UTC offset that PostgreSQL preserves.
            set_committed_value(sale, "paid_at", sale.paid_at.replace(tzinfo=UTC))
        return sale

    def assess_at_fixed_time(paid_at):
        return assess_window(paid_at, now=datetime(2026, 11, 13, tzinfo=UTC))

    monkeypatch.setattr(routes, "get_refund_sale_for_admin", load_sale_with_aware_timestamp)
    monkeypatch.setattr(routes, "assess_voluntary_refund_window", assess_at_fixed_time)


def test_admin_paid_product_shows_utc_deadline(
    auth_client, db_session, fixed_refund_review_clock
):
    sale = add_paid_sale(db_session)
    add_sale_item(sale, SaleItemType.PRODUCT)
    sale.paid_at = datetime(2026, 11, 12, 10, 23, 45, 123456, tzinfo=UTC)
    db_session.commit()

    detail = auth_client.get(f"/admin/sales/{sale.id}")

    assert detail.status_code == 200
    assert "Voluntary SmartBudget refund window" in detail.text
    assert "<dd>within_window</dd>" in detail.text
    assert "The voluntary 14-day SmartBudget refund window is still open." in detail.text
    assert "Deadline (UTC)" in detail.text
    assert 'datetime="2026-11-26T10:23:45.123456+00:00"' in detail.text
    assert "2026-11-26 10:23:45.123456+00:00</time>" in detail.text
    assert "does not determine whether a refund may be authorized." in detail.text
    assert db_session.query(RefundOperation).count() == 0


@pytest.mark.parametrize(
    ("payment_status", "item_type"),
    [
        (PaymentStatus.PAID, SaleItemType.SERVICE),
        (PaymentStatus.PENDING, SaleItemType.PRODUCT),
        (PaymentStatus.FAILED, SaleItemType.PRODUCT),
        (PaymentStatus.REFUNDED, SaleItemType.PRODUCT),
    ],
)
def test_admin_omits_refund_window_for_inapplicable_sales(
    auth_client, db_session, payment_status, item_type
):
    sale = add_paid_sale(db_session)
    add_sale_item(sale, item_type)
    sale.payment_status = payment_status
    db_session.commit()

    detail = auth_client.get(f"/admin/sales/{sale.id}")

    assert detail.status_code == 200
    assert "Voluntary SmartBudget refund window" not in detail.text


def test_admin_refund_workflow_requires_authentication(client, db_session):
    sale = add_paid_sale(db_session)
    add_sale_item(sale, SaleItemType.PRODUCT)
    db_session.commit()

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


@pytest.mark.parametrize(
    ("paid_at", "window_status", "explanation"),
    [
        (
            None,
            "manual_review",
            "The voluntary refund deadline cannot be determined.",
        ),
        (
            datetime(2026, 10, 1, tzinfo=UTC),
            "expired",
            "The voluntary 14-day window has expired. Other refund grounds may still require review.",
        ),
    ],
)
def test_admin_full_refund_flow_is_visible_and_confirmed(
    auth_client, db_session, fixed_refund_review_clock, paid_at, window_status, explanation
):
    sale = add_paid_sale(db_session)
    add_sale_item(sale, SaleItemType.PRODUCT)
    sale.paid_at = paid_at
    db_session.commit()

    detail = auth_client.get(f"/admin/sales/{sale.id}")
    assert db_session.query(RefundOperation).count() == 0
    started = auth_client.post(
        f"/admin/sales/{sale.id}/refund/start",
        data={"confirmation": "start_full_refund"},
        follow_redirects=False,
    )
    operation = db_session.query(RefundOperation).one()
    before_detail = (operation.id, operation.status, operation.updated_at)
    pending_detail = auth_client.get(f"/admin/sales/{sale.id}")
    db_session.refresh(operation)
    assert (operation.id, operation.status, operation.updated_at) == before_detail
    confirmed = auth_client.post(
        f"/admin/sales/{sale.id}/refund/confirm",
        data={"acknowledgement": "verified_full_refund_in_lava_top"},
        follow_redirects=False,
    )

    assert detail.status_code == 200
    assert f"<dd>{window_status}</dd>" in detail.text
    assert explanation in detail.text
    assert ("Deadline (UTC)" in detail.text) == (paid_at is not None)
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
