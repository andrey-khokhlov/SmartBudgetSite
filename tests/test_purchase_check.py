from datetime import UTC, datetime
from decimal import Decimal

from app.models.enums import PaymentStatus
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem


FORBIDDEN_PUBLIC_KEYS = {
    "sale_id",
    "sale_item_id",
    "product_id",
    "created_at",
    "payment_provider",
    "external_payment_id",
}


def _create_product_sale(
    db_session,
    *,
    email: str,
    payment_status: PaymentStatus,
    include_product_item: bool = True,
    slug: str | None = None,
    product_name: str = "SmartBudget",
    edition: str = "Standard",
) -> tuple[Product, SaleItem | None]:
    product = Product(
        family_slug="smartbudget",
        slug=slug or f"smartbudget-{email.split('@')[0]}",
        name=product_name,
        edition=edition,
        status="in_sale",
        archive_path="test/path.zip",
    )
    db_session.add(product)
    db_session.flush()

    sale = Sale(
        product_id=product.id,
        customer_email=email,
        amount=Decimal("10.00"),
        currency="EUR",
        payment_status=payment_status,
        created_at=datetime.now(UTC),
    )
    db_session.add(sale)
    db_session.flush()

    item = None
    if include_product_item:
        item = SaleItem(
            sale_id=sale.id,
            item_type="product",
            product_id=product.id,
            item_name=product.name,
            currency_code="EUR",
            amount=Decimal("10.00"),
            quantity=1,
        )
        db_session.add(item)

    db_session.commit()
    return product, item


def test_check_purchase_not_found_returns_boolean_only(client):
    response = client.post(
        "/v1/check-purchase",
        json={"email": "unknown@example.com"},
    )

    assert response.status_code == 200
    assert response.json() == {"verified": False}
    assert FORBIDDEN_PUBLIC_KEYS.isdisjoint(response.json())


def test_check_purchase_paid_product_returns_one_safe_purchase(client, db_session):
    _create_product_sale(
        db_session,
        email="buyer@example.com",
        payment_status=PaymentStatus.PAID,
    )

    response = client.post(
        "/v1/check-purchase",
        json={"email": "BUYER@example.com"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["verified"] is True
    assert len(data["purchases"]) == 1
    assert data["purchases"][0]["product_name"] == "SmartBudget"
    assert data["purchases"][0]["edition"] == "Standard"
    assert data["purchases"][0]["purchase_reference"].startswith("FP-")
    assert FORBIDDEN_PUBLIC_KEYS.isdisjoint(data)
    assert FORBIDDEN_PUBLIC_KEYS.isdisjoint(data["purchases"][0])


def test_check_purchase_paid_products_returns_multiple_safe_purchases(
    client,
    db_session,
):
    _create_product_sale(
        db_session,
        email="multi@example.com",
        payment_status=PaymentStatus.PAID,
        slug="smartbudget-multi-standard",
        edition="Standard",
    )
    _create_product_sale(
        db_session,
        email="multi@example.com",
        payment_status=PaymentStatus.PAID,
        slug="smartbudget-multi-pro",
        edition="Pro",
    )

    response = client.post(
        "/v1/check-purchase",
        json={"email": "multi@example.com"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["verified"] is True
    assert [purchase["edition"] for purchase in data["purchases"]] == [
        "Standard",
        "Pro",
    ]
    assert len(
        {purchase["purchase_reference"] for purchase in data["purchases"]}
    ) == 2
    for purchase in data["purchases"]:
        assert set(purchase) == {
            "purchase_reference",
            "product_name",
            "edition",
        }


def test_check_purchase_empty_email(client):
    response = client.post(
        "/v1/check-purchase",
        json={"email": ""},
    )

    assert response.status_code == 422


def test_product_invalid_edition(db_session):
    try:
        product = Product(
            family_slug="smartbudget",
            slug="smartbudget-invalid",
            name="SmartBudget",
            edition="InvalidEdition",
            status="in_sale",
            archive_path="test/path.zip",
        )
        db_session.add(product)
        db_session.flush()

        assert False, "Expected ValueError was not raised"

    except ValueError as error:
        assert "Invalid edition" in str(error)


def test_check_purchase_paid_sale_without_product_item_is_not_verified(
    client,
    db_session,
):
    _create_product_sale(
        db_session,
        email="legacy-only@example.com",
        payment_status=PaymentStatus.PAID,
        include_product_item=False,
    )

    response = client.post(
        "/v1/check-purchase",
        json={"email": "legacy-only@example.com"},
    )

    assert response.status_code == 200
    assert response.json() == {"verified": False}


def test_check_purchase_unpaid_product_item_is_not_verified(client, db_session):
    _create_product_sale(
        db_session,
        email="pending@example.com",
        payment_status=PaymentStatus.PENDING,
    )

    response = client.post(
        "/v1/check-purchase",
        json={"email": "pending@example.com"},
    )

    assert response.status_code == 200
    assert response.json() == {"verified": False}


def test_check_purchase_service_only_is_not_verified(client, db_session):
    from app.models.service_addon import ServiceAddon

    service_addon = ServiceAddon(
        code="consultation_1h_int_service_only_purchase_test",
        name="Standalone consultation",
        service_type="consultation",
        usage_type="standalone",
        family_slug="smartbudget",
        package_code="INT",
        currency_code="EUR",
        amount=Decimal("79.00"),
        is_active=True,
    )
    db_session.add(service_addon)
    db_session.flush()

    sale = Sale(
        product_id=None,
        customer_email="service_only@example.com",
        amount=Decimal("79.00"),
        currency="EUR",
        payment_status=PaymentStatus.PAID,
        created_at=datetime.now(UTC),
    )
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(
            sale_id=sale.id,
            item_type="service",
            service_addon_id=service_addon.id,
            item_name="Standalone consultation",
            currency_code="EUR",
            amount=Decimal("79.00"),
            quantity=1,
        )
    )
    db_session.commit()

    response = client.post(
        "/v1/check-purchase",
        json={"email": "service_only@example.com"},
    )

    assert response.status_code == 200
    assert response.json() == {"verified": False}
