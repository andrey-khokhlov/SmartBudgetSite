from decimal import Decimal

from fastapi.testclient import TestClient

from app.models.payment_provider_offer import PaymentProviderOffer
from app.models.product import Product
from app.models.product_price import ProductPrice
from app.models.product_release import ProductRelease

SHARED_OFFER_ID = "cc1137ac-f8dd-4d51-bd37-738431d6461d"


def create_product(
    db_session,
    slug: str,
    *,
    status: str = "in_sale",
    with_price: bool = True,
    with_release: bool = True,
    offer_id: str | None = None,
) -> Product:
    product = Product(
        family_slug="smartbudget",
        slug=slug,
        name="SmartBudget",
        edition="Standard",
        archive_path="",
        status=status,
    )
    db_session.add(product)
    db_session.flush()

    if with_price:
        db_session.add(
            ProductPrice(
                product_id=product.id,
                currency_code="RUB",
                amount=Decimal("50.00"),
                is_active=True,
            )
        )
    if with_release:
        db_session.add(
            ProductRelease(
                product_id=product.id,
                version="1.0",
                storage_provider="cloudflare_r2",
                storage_key=f"product-releases/{product.id}/admin-provider-test",
                original_filename="SmartBudget.zip",
                is_active=True,
            )
        )
    if offer_id is not None:
        db_session.add(
            PaymentProviderOffer(
                product_id=product.id,
                provider="lava_top",
                external_offer_id=offer_id,
            )
        )

    db_session.commit()
    db_session.refresh(product)
    return product


def get_lava_top_mapping(db_session, product: Product):
    return (
        db_session.query(PaymentProviderOffer)
        .filter(
            PaymentProviderOffer.product_id == product.id,
            PaymentProviderOffer.provider == "lava_top",
        )
        .one_or_none()
    )


def test_admin_product_page_shows_existing_lava_top_mapping(
    auth_client: TestClient,
    db_session,
):
    product = create_product(
        db_session,
        "admin-provider-existing",
        offer_id=SHARED_OFFER_ID,
    )

    response = auth_client.get(f"/admin/products/{product.id}/edit")

    assert response.status_code == 200
    assert "Provider:</strong> lava_top" in response.text
    assert SHARED_OFFER_ID in response.text


def test_admin_product_page_shows_unconfigured_lava_top_state(
    auth_client: TestClient,
    db_session,
):
    product = create_product(db_session, "admin-provider-unconfigured")

    response = auth_client.get(f"/admin/products/{product.id}/edit")

    assert response.status_code == 200
    assert "Current external Offer ID:" in response.text
    assert "Not configured" in response.text


def test_admin_can_create_lava_top_mapping(auth_client, db_session):
    product = create_product(db_session, "admin-provider-create")

    response = auth_client.post(
        f"/admin/products/{product.id}/payment-provider-offers/lava-top",
        data={"external_offer_id": f"  {SHARED_OFFER_ID}  "},
        follow_redirects=False,
    )

    db_session.expire_all()
    mapping = get_lava_top_mapping(db_session, product)
    assert response.status_code == 303
    assert response.headers["location"].endswith("provider_saved=created")
    assert mapping is not None
    assert mapping.external_offer_id == SHARED_OFFER_ID


def test_admin_can_update_lava_top_mapping(auth_client, db_session):
    product = create_product(
        db_session,
        "admin-provider-update",
        offer_id="old-offer-id",
    )

    response = auth_client.post(
        f"/admin/products/{product.id}/payment-provider-offers/lava-top",
        data={"external_offer_id": "new-offer-id"},
        follow_redirects=False,
    )

    db_session.expire_all()
    mapping = get_lava_top_mapping(db_session, product)
    assert response.status_code == 303
    assert response.headers["location"].endswith("provider_saved=updated")
    assert mapping is not None
    assert mapping.external_offer_id == "new-offer-id"


def test_blank_external_offer_id_is_rejected_without_changing_mapping(
    auth_client,
    db_session,
):
    product = create_product(
        db_session,
        "admin-provider-blank",
        offer_id="existing-offer-id",
    )

    response = auth_client.post(
        f"/admin/products/{product.id}/payment-provider-offers/lava-top",
        data={"external_offer_id": "   "},
        follow_redirects=False,
    )

    db_session.expire_all()
    mapping = get_lava_top_mapping(db_session, product)
    assert response.status_code == 303
    assert "provider_error=invalid_external_offer_id" in response.headers["location"]
    assert mapping is not None
    assert mapping.external_offer_id == "existing-offer-id"


def test_shared_offer_id_can_be_assigned_without_modifying_other_product(
    auth_client,
    db_session,
):
    existing_product = create_product(
        db_session,
        "admin-provider-shared-existing",
        offer_id=SHARED_OFFER_ID,
    )
    new_product = create_product(db_session, "admin-provider-shared-new")
    existing_mapping = get_lava_top_mapping(db_session, existing_product)
    existing_mapping_id = existing_mapping.id

    response = auth_client.post(
        f"/admin/products/{new_product.id}/payment-provider-offers/lava-top",
        data={"external_offer_id": SHARED_OFFER_ID},
        follow_redirects=False,
    )

    db_session.expire_all()
    mappings = (
        db_session.query(PaymentProviderOffer)
        .filter(
            PaymentProviderOffer.provider == "lava_top",
            PaymentProviderOffer.external_offer_id == SHARED_OFFER_ID,
        )
        .order_by(PaymentProviderOffer.product_id)
        .all()
    )
    existing_mapping = get_lava_top_mapping(db_session, existing_product)
    assert response.status_code == 303
    assert len(mappings) == 2
    assert {mapping.product_id for mapping in mappings} == {
        existing_product.id,
        new_product.id,
    }
    assert existing_mapping.id == existing_mapping_id
    assert existing_mapping.external_offer_id == SHARED_OFFER_ID


def test_checkout_readiness_reports_missing_price(auth_client, db_session):
    product = create_product(
        db_session,
        "admin-readiness-no-price",
        with_price=False,
        offer_id=SHARED_OFFER_ID,
    )

    response = auth_client.get(f"/admin/products/{product.id}/edit")

    assert "Checkout ready:</strong>\n                No" in response.text
    assert "active ProductPrice" in response.text


def test_checkout_readiness_reports_missing_active_release(auth_client, db_session):
    product = create_product(
        db_session,
        "admin-readiness-no-release",
        with_release=False,
        offer_id=SHARED_OFFER_ID,
    )

    response = auth_client.get(f"/admin/products/{product.id}/edit")

    assert "Checkout ready:</strong>\n                No" in response.text
    assert "active ProductRelease" in response.text


def test_checkout_readiness_reports_missing_provider_mapping(auth_client, db_session):
    product = create_product(db_session, "admin-readiness-no-provider")

    response = auth_client.get(f"/admin/products/{product.id}/edit")

    assert "Checkout ready:</strong>\n                No" in response.text
    assert "Lava.top PaymentProviderOffer" in response.text


def test_checkout_readiness_reports_non_sale_status(auth_client, db_session):
    product = create_product(
        db_session,
        "admin-readiness-status",
        status="in_development",
        offer_id=SHARED_OFFER_ID,
    )

    response = auth_client.get(f"/admin/products/{product.id}/edit")

    assert "Checkout ready:</strong>\n                No" in response.text
    assert "status is not in_sale" in response.text


def test_checkout_readiness_reports_ready_when_all_prerequisites_exist(
    auth_client,
    db_session,
):
    product = create_product(
        db_session,
        "admin-readiness-ready",
        offer_id=SHARED_OFFER_ID,
    )

    response = auth_client.get(f"/admin/products/{product.id}/edit")

    assert "Checkout ready:</strong>\n                Yes" in response.text
    assert "Missing prerequisites:" not in response.text


def test_unauthorized_request_cannot_create_provider_mapping(client, db_session):
    product = create_product(db_session, "admin-provider-unauthorized")

    response = client.post(
        f"/admin/products/{product.id}/payment-provider-offers/lava-top",
        data={"external_offer_id": SHARED_OFFER_ID},
    )

    db_session.expire_all()
    assert response.status_code == 403
    assert get_lava_top_mapping(db_session, product) is None
