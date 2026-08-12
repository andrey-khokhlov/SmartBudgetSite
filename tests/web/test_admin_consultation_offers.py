from decimal import Decimal

from app.models.product import Product
from app.models.service_addon import ServiceAddon


def add_product(db_session):
    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-ru-standard-admin-offer-route-test",
        name="SmartBudget",
        edition="Standard",
        archive_path="",
        status="in_development",
    )
    db_session.add(product)
    db_session.commit()


def test_consultation_offer_routes_require_admin(client):
    for method, path in (
        ("get", "/admin/consultation-offers"),
        ("get", "/admin/consultation-offers/new"),
        ("post", "/admin/consultation-offers/new"),
        ("get", "/admin/consultation-offers/1/edit"),
        ("post", "/admin/consultation-offers/1/edit"),
    ):
        response = getattr(client, method)(path, follow_redirects=False)
        assert response.status_code == 403


def test_admin_can_create_and_list_temporary_rub_offer(
    auth_client,
    db_session,
):
    add_product(db_session)
    response = auth_client.post(
        "/admin/consultation-offers/new",
        data={
            "family_slug": "smartbudget",
            "package_code": "RU",
            "usage_type": "addon",
            "currency_code": "RUB",
            "name": "Temporary validation consultation",
            "amount": "50.00",
            "status": "active",
            "code": "founder-controlled-code",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    offer = db_session.query(ServiceAddon).one()
    assert offer.code != "founder-controlled-code"
    assert offer.service_type == "consultation"
    assert offer.amount == Decimal("50.00")
    listing = auth_client.get("/admin/consultation-offers")
    assert listing.status_code == 200
    assert "Temporary validation consultation" in listing.text
    assert "Active" in listing.text
    assert "Technical code" not in listing.text
    assert offer.code not in listing.text
    assert "delete" not in listing.text.lower()


def test_create_form_uses_controlled_fields_and_defaults_to_active(
    auth_client,
    db_session,
):
    add_product(db_session)

    response = auth_client.get("/admin/consultation-offers/new")

    assert response.status_code == 200
    assert 'name="service_type"' not in response.text
    assert "Service type" not in response.text
    for field_name in (
        "family_slug",
        "package_code",
        "usage_type",
        "currency_code",
        "status",
    ):
        assert f'<select id="' in response.text
        assert f'name="{field_name}"' in response.text
    assert 'name="code"' not in response.text
    assert 'type="checkbox"' not in response.text
    assert '<option value="active" selected>Active</option>' in response.text
    assert '<option value="inactive" >Inactive</option>' in response.text


def test_edit_endpoint_ignores_identity_fields_and_updates_mutable_fields(
    auth_client,
    db_session,
):
    add_product(db_session)
    offer = ServiceAddon(
        code="historical-code",
        family_slug="smartbudget",
        package_code="RU",
        service_type="consultation",
        usage_type="addon",
        currency_code="RUB",
        name="Old name",
        amount=Decimal("3500.00"),
        is_active=True,
    )
    db_session.add(offer)
    db_session.commit()

    response = auth_client.post(
        f"/admin/consultation-offers/{offer.id}/edit",
        data={
            "name": "New name",
            "amount": "50.00",
            "status": "inactive",
            "code": "changed",
            "family_slug": "other",
            "package_code": "INT",
            "service_type": "support",
            "usage_type": "standalone",
            "currency_code": "EUR",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    db_session.refresh(offer)
    assert offer.name == "New name"
    assert offer.amount == Decimal("50.00")
    assert offer.is_active is False
    assert (
        offer.code,
        offer.family_slug,
        offer.package_code,
        offer.service_type,
        offer.usage_type,
        offer.currency_code,
    ) == (
        "historical-code",
        "smartbudget",
        "RU",
        "consultation",
        "addon",
        "RUB",
    )


def test_edit_form_shows_identity_as_metadata_and_current_inactive_status(
    auth_client,
    db_session,
):
    add_product(db_session)
    offer = ServiceAddon(
        code="diagnostic-code",
        family_slug="smartbudget",
        package_code="RU",
        service_type="consultation",
        usage_type="standalone",
        currency_code="RUB",
        name="Inactive consultation",
        amount=Decimal("50.00"),
        is_active=False,
    )
    db_session.add(offer)
    db_session.commit()

    response = auth_client.get(f"/admin/consultation-offers/{offer.id}/edit")

    assert response.status_code == 200
    assert 'aria-label="Immutable offer identity"' in response.text
    assert "diagnostic-code" in response.text
    assert "Service type" not in response.text
    for field_name in (
        "code",
        "family_slug",
        "package_code",
        "service_type",
        "usage_type",
        "currency_code",
    ):
        assert f'name="{field_name}"' not in response.text
    assert '<option value="inactive" selected>Inactive</option>' in response.text
    assert 'type="checkbox"' not in response.text


def test_edit_active_status_maps_to_true(auth_client, db_session):
    add_product(db_session)
    offer = ServiceAddon(
        code="inactive-to-active-code",
        family_slug="smartbudget",
        package_code="RU",
        service_type="consultation",
        usage_type="addon",
        currency_code="RUB",
        name="Inactive consultation",
        amount=Decimal("50.00"),
        is_active=False,
    )
    db_session.add(offer)
    db_session.commit()

    response = auth_client.post(
        f"/admin/consultation-offers/{offer.id}/edit",
        data={"name": offer.name, "amount": "50.00", "status": "active"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    db_session.refresh(offer)
    assert offer.is_active is True


def test_create_ignores_browser_service_type_and_persists_consultation(
    auth_client,
    db_session,
):
    add_product(db_session)
    response = auth_client.post(
        "/admin/consultation-offers/new",
        data={
            "family_slug": "smartbudget",
            "package_code": "RU",
            "service_type": "support",
            "usage_type": "addon",
            "currency_code": "RUB",
            "name": "Consultation only",
            "amount": "50.00",
            "status": "active",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert db_session.query(ServiceAddon).one().service_type == "consultation"


def test_invalid_controlled_value_fails_without_creation(auth_client, db_session):
    add_product(db_session)
    response = auth_client.post(
        "/admin/consultation-offers/new",
        data={
            "family_slug": "smartbudget",
            "package_code": "RU",
            "usage_type": "unsupported",
            "currency_code": "RUB",
            "name": "Invalid",
            "amount": "50.00",
            "status": "active",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "error=invalid_input" in response.headers["location"]
    assert db_session.query(ServiceAddon).count() == 0


def test_invalid_status_fails_safely(auth_client, db_session):
    add_product(db_session)
    response = auth_client.post(
        "/admin/consultation-offers/new",
        data={
            "family_slug": "smartbudget",
            "package_code": "RU",
            "usage_type": "addon",
            "currency_code": "RUB",
            "name": "Invalid status",
            "amount": "50.00",
            "status": "unexpected",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "error=invalid_input" in response.headers["location"]
    assert db_session.query(ServiceAddon).count() == 0
