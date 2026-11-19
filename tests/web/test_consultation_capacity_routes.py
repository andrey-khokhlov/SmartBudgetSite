from unittest.mock import Mock

import pytest

from app.core.config import settings
from app.models.sale import Sale
from app.models.service_addon import ServiceAddon
from app.services.consultation_capacity_service import (
    ConsultationCapacityUnavailableError,
)
from app.services.payment_service import initiate_lava_top_product_checkout
from tests.services.test_consultation_capacity import add_available_rights
from tests.web.test_checkout_initiation import (
    create_checkout_catalog,
    install_successful_provider,
)
from tests.web.test_public_consultations import seed_consultations


@pytest.mark.parametrize(
    ("lang", "currency", "message"),
    [
        ("en", "EUR", "Consultation checkout is currently unavailable."),
        ("ru", "RUB", "Оформление консультации сейчас недоступно."),
    ],
)
def test_capacity_blocks_catalog_get_and_stale_post_then_restores(
    client, db_session, monkeypatch, lang, currency, message
):
    catalog = seed_consultations(db_session)
    path = f"/consultations/checkout/{catalog[currency]}?lang={lang}"
    assert client.get(path, params={"currency": currency}).status_code == 200
    rights = add_available_rights(db_session, 4, catalog[currency])
    provider = Mock()
    monkeypatch.setattr("app.services.payment_service.create_invoice", provider)

    page = client.get(f"/consultations?lang={lang}")
    checkout = client.get(path, params={"currency": currency})
    post = client.post(
        path, data={"currency": currency, "customer_email": "buyer@example.com"}
    )
    assert (page.status_code, checkout.status_code, post.status_code) == (200, 503, 503)
    assert 'href="/consultations/checkout/' not in page.text
    for response in (page, checkout, post):
        assert message in response.text
        for private in ("outstanding", "threshold", "Capacity limit", "порог", "лимит"):
            assert private not in response.text
        assert "capacity" not in response.context
    provider.assert_not_called()
    assert db_session.query(Sale).count() == 4

    rights[0].status = "booked"
    db_session.commit()
    assert client.get(path, params={"currency": currency}).status_code == 200
    assert (
        'href="/consultations/checkout/'
        in client.get(f"/consultations?lang={lang}").text
    )


def test_enabled_bundle_is_blocked_and_product_only_checkout_still_works(
    client, db_session, enable_bundle_checkout, monkeypatch
):
    catalog = seed_consultations(db_session)
    add_available_rights(db_session, 4, catalog["RUB"])
    product = create_checkout_catalog(db_session, slug="smartbudget-int-standard")
    path = f"/checkout/{product.slug}"
    post_data = {
        "currency": "EUR",
        "customer_email": "buyer@example.com",
        "consultation": "1",
    }
    captured = {}
    url = install_successful_provider(monkeypatch, captured)
    assert (
        'class="product-addon__checkbox"'
        not in client.get("/products/smartbudget/buy").text
    )
    checkout = client.get(
        path, params={"currency": "EUR", "consultation": 1, "lang": "en"}
    )
    assert "Consultation checkout is currently unavailable." in checkout.text
    assert 'class="checkout-form"' not in checkout.text
    assert client.post(path, data=post_data).status_code == 503
    with pytest.raises(ConsultationCapacityUnavailableError):
        initiate_lava_top_product_checkout(
            db_session,
            product_slug=product.slug,
            customer_email=post_data["customer_email"],
            currency="EUR",
            include_consultation=True,
        )
    assert not captured
    assert db_session.query(Sale).count() == 4

    response = client.post(
        path, data=post_data | {"consultation": "0"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == url
    sale = db_session.query(Sale).filter_by(product_id=product.id).one()
    (item,) = sale.items
    assert item.item_type == "product"


def test_admin_capacity_action_is_protected_and_preserves_offers(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "SECRET_KEY", "capacity-csrf-test-secret")
    catalog = seed_consultations(db_session)
    listing = "/admin/consultation-offers"
    path = f"{listing}/capacity"
    assert client.post(path, data={"action": "suspend"}).status_code == 403
    client.cookies.set("admin_token", settings.ADMIN_TOKEN)
    assert client.post(path, data={"action": "suspend"}).status_code == 403
    page = client.get(listing)
    assert "Outstanding consultations</dt><dd>0" in page.text
    assert "Warning threshold</dt><dd>3" in page.text
    assert "Capacity limit</dt><dd>4" in page.text
    assert "New consultation sales</dt><dd>Available" in page.text
    assert "Manual suspension</dt><dd>Inactive" in page.text

    def submit(page, action):
        return client.post(
            path,
            data={
                "action": action,
                "csrf_cookie_id": page.context["csrf_cookie_id"],
                "csrf_token": page.context["csrf_token"],
            },
            follow_redirects=False,
        )

    assert submit(page, "invalid").status_code == 400
    assert submit(page, "suspend").status_code == 303
    page = client.get(listing)
    assert "Manual suspension</dt><dd>Active" in page.text
    assert "New consultation sales</dt><dd>Unavailable" in page.text
    assert db_session.get(ServiceAddon, catalog["EUR"]).is_active
    assert (
        client.get(f"/consultations/checkout/{catalog['EUR']}?currency=EUR").status_code
        == 503
    )
    assert submit(page, "resume").status_code == 303
    assert (
        client.get(f"/consultations/checkout/{catalog['EUR']}?currency=EUR").status_code
        == 200
    )
