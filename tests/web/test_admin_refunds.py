from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm.attributes import set_committed_value

from app.core.config import settings
from app.models.enums import PaymentStatus, SaleItemType
from app.models.product import Product
from app.models.refund_operation import RefundConfirmationMethod, RefundOperation
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.service_addon import ServiceAddon
from app.services.refund_service import start_full_refund
from app.web import routes


ORIGINAL_ACK = {"acknowledgement": "verified_full_refund_in_lava_top"}
ALTERNATIVE_ACKS = {
    "customer_agreed": "yes",
    "transfer_verified": "yes",
    "evidence_retained": "yes",
    "original_refund_not_executed": "yes",
}
START_ACK = {"confirmation": "start_full_refund"}


@pytest.fixture(autouse=True)
def refund_csrf_secret(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "test-refund-operation-csrf")


def refund_csrf(page):
    return {
        "csrf_id": page.context["refund_csrf_id"],
        "csrf_token": page.context["refund_csrf_token"],
    }


def add_paid_sale(db_session, *, invoice="admin-refund-invoice") -> Sale:
    sale = Sale(
        customer_email="admin-refund@example.com",
        amount=Decimal("50.00"),
        currency="RUB",
        payment_provider="lava_top",
        payment_status=PaymentStatus.PAID,
        external_payment_id=invoice,
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


def test_admin_sale_detail_displays_unresolved_calendly_revocation(auth_client, db_session):
    from tests.services.test_consultation_entitlement_service import create_test_consultation_entitlement

    entitlement = create_test_consultation_entitlement(db_session)
    sale_id = entitlement.sale_item.sale_id
    entitlement.calendly_revoke_outcome = "provider_not_found"
    entitlement.calendly_revoke_next_at = entitlement.expires_at
    db_session.commit()
    response = auth_client.get(f"/admin/sales/{sale_id}")
    assert response.status_code == 200
    assert "Calendly Share revocation unresolved: provider not found." in response.text
    assert "Next attempt (UTC)" in response.text


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
            data=ORIGINAL_ACK,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/admin/sales/{sale.id}/refund/confirm-alternative",
            data=ALTERNATIVE_ACKS,
        ).status_code
        == 403
    )


def test_admin_requires_explicit_confirmation_for_both_actions(auth_client, db_session):
    sale = add_paid_sale(db_session)
    csrf = refund_csrf(auth_client.get(f"/admin/sales/{sale.id}"))

    missing_start = auth_client.post(f"/admin/sales/{sale.id}/refund/start", data=csrf)
    wrong_start = auth_client.post(
        f"/admin/sales/{sale.id}/refund/start",
        data=csrf | {"confirmation": "yes"},
    )

    assert missing_start.status_code == 422
    assert wrong_start.status_code == 400
    assert db_session.query(RefundOperation).count() == 0

    started = auth_client.post(
        f"/admin/sales/{sale.id}/refund/start",
        data=csrf | START_ACK,
        follow_redirects=False,
    )
    missing_confirm = auth_client.post(
        f"/admin/sales/{sale.id}/refund/confirm", data=csrf
    )
    wrong_confirm = auth_client.post(
        f"/admin/sales/{sale.id}/refund/confirm",
        data=csrf | {"acknowledgement": "sent"},
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
        data=refund_csrf(detail) | START_ACK,
        follow_redirects=False,
    )
    operation = db_session.query(RefundOperation).one()
    before_detail = (operation.id, operation.status, operation.updated_at)
    pending_detail = auth_client.get(f"/admin/sales/{sale.id}")
    db_session.refresh(operation)
    assert (operation.id, operation.status, operation.updated_at) == before_detail
    confirmed = auth_client.post(
        f"/admin/sales/{sale.id}/refund/confirm",
        data=refund_csrf(pending_detail) | ORIGINAL_ACK,
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
    assert operation.confirmation_method == RefundConfirmationMethod.ORIGINAL_PROVIDER


@pytest.mark.parametrize(
    ("action", "acknowledgements"),
    [
        ("start", START_ACK),
        ("confirm", ORIGINAL_ACK),
        ("confirm-alternative", ALTERNATIVE_ACKS),
    ],
)
def test_admin_refund_csrf_is_bound_to_sale_before_mutation(
    auth_client, db_session, action, acknowledgements
):
    sale_id = add_paid_sale(db_session).id
    other_id = add_paid_sale(db_session, invoice="other-csrf-sale").id
    db_session.rollback()
    if action != "start":
        start_full_refund(db_session, sale_id=sale_id)
    path = f"/admin/sales/{sale_id}/refund/{action}"
    csrf = refund_csrf(auth_client.get(f"/admin/sales/{sale_id}"))
    other = auth_client.get(f"/admin/sales/{other_id}")
    foreign_csrf = refund_csrf(other)
    foreign_cookie = f"refund_operation_csrf_{foreign_csrf['csrf_id']}"
    auth_client.cookies.set(
        foreign_cookie,
        other.cookies[foreign_cookie],
        path=f"/admin/sales/{sale_id}/refund",
    )
    for form in ({}, csrf | {"csrf_token": "0" * 64}, foreign_csrf):
        assert auth_client.post(path, data=acknowledgements | form).status_code == 403

    operation = (
        db_session.query(RefundOperation).filter_by(sale_id=sale_id).one_or_none()
    )
    if action == "start":
        assert operation is None
    else:
        assert operation.status == "pending" and operation.confirmation_method is None
    assert db_session.get(Sale, sale_id).payment_status == PaymentStatus.PAID


@pytest.mark.parametrize("missing", ALTERNATIVE_ACKS)
def test_alternative_confirmation_requires_every_acknowledgement(
    auth_client, db_session, missing
):
    sale_id = add_paid_sale(db_session).id
    db_session.rollback()
    start_full_refund(db_session, sale_id=sale_id)
    csrf = refund_csrf(auth_client.get(f"/admin/sales/{sale_id}"))
    incomplete = {
        name: value for name, value in ALTERNATIVE_ACKS.items() if name != missing
    }
    response = auth_client.post(
        f"/admin/sales/{sale_id}/refund/confirm-alternative", data=csrf | incomplete
    )
    assert response.status_code == 400
    assert db_session.get(Sale, sale_id).payment_status == PaymentStatus.PAID
    operation = db_session.query(RefundOperation).one()
    assert operation.status == "pending" and operation.confirmation_method is None


def test_admin_confirmation_records_alternative_method_and_rejects_switch(
    auth_client, db_session
):
    sale_id = add_paid_sale(db_session).id
    db_session.rollback()
    start_full_refund(db_session, sale_id=sale_id)
    path = f"/admin/sales/{sale_id}"
    page = auth_client.get(path)
    assert "Confirm alternative refund" in page.text
    assert "I verified the full refund in Lava.top." in page.text
    assert "Bank or card settlement requires separate evidence." in page.text
    csrf = refund_csrf(page)

    def post(action, data):
        return auth_client.post(
            f"{path}/refund/{action}", data=csrf | data, follow_redirects=False
        )

    invalid = post(
        "confirm-alternative",
        ALTERNATIVE_ACKS
        | {"disposition_exception_reason": "unexpected transfer details"},
    )
    assert (
        invalid.status_code == 400 and "unexpected transfer details" not in invalid.text
    )
    assert (
        post("confirm-alternative", ALTERNATIVE_ACKS)
        .headers["location"]
        .endswith("=applied")
    )
    assert (
        post("confirm-alternative", ALTERNATIVE_ACKS)
        .headers["location"]
        .endswith("=idempotent")
    )
    assert post("confirm", ORIGINAL_ACK).headers["location"].endswith("=conflict")
    assert "Alternative transfer</dd>" in auth_client.get(path).text
    operation = db_session.query(RefundOperation).one()
    assert (
        operation.confirmation_method == RefundConfirmationMethod.ALTERNATIVE_TRANSFER
    )
    assert operation.exceptional_confirmation_reason is None
