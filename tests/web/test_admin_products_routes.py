from __future__ import annotations
import re
from typing import Any
from fastapi.testclient import TestClient
from app.models.product import Product
from decimal import Decimal
from app.services.product_service import set_product_price
from tests.conftest import auth_client


def test_admin_products_list_page_renders_products(
    auth_client: TestClient,
    db_session: Any,
) -> None:
    """
    Verifies:
    - /admin/products returns 200
    - product list page renders saved products
    """

    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-ru-standard",
        name="SmartBudget",
        edition="Standard",

        archive_path="products/smartbudget-ru-standard/v1/archive.zip",
        status="in_sale",
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)

    set_product_price(
        db=db_session,
        product_id=product.id,
        currency_code="RUB",
        amount=Decimal("49.00"),
    )

    response = auth_client.get("/admin/products")

    assert response.status_code == 200
    assert "SmartBudget" in response.text
    assert "Standard" in response.text
    assert "in_sale" in response.text
    assert "49.00 RUB" in response.text
    assert f'href="/admin/products/{product.id}/edit"' in response.text
    assert f'href="/products/{product.id}/releases"' in response.text


def _assert_product_form_cancel_action(response) -> None:
    assert response.status_code == 200
    assert re.search(
        r'<a href="/admin/products" class="btn-secondary">Cancel</a>',
        response.text,
    )
    assert not re.search(r'<button[^>]*>\s*Cancel\s*</button>', response.text)


def test_admin_product_create_form_has_non_submit_cancel_action(auth_client) -> None:
    response = auth_client.get("/admin/products/new")

    _assert_product_form_cancel_action(response)
    assert 'action="/admin/products/new"' in response.text
    assert re.search(r'<button type="submit"[^>]*>Save</button>', response.text)


def test_admin_product_edit_form_has_non_submit_cancel_action(
    auth_client: TestClient,
    db_session: Any,
) -> None:
    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-ru-edit-navigation-test",
        name="SmartBudget",
        edition="Standard",
        archive_path="",
        status="in_sale",
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    set_product_price(
        db=db_session,
        product_id=product.id,
        currency_code="RUB",
        amount=Decimal("49.00"),
    )

    response = auth_client.get(f"/admin/products/{product.id}/edit")

    _assert_product_form_cancel_action(response)
    assert f'action="/admin/products/{product.id}/edit"' in response.text
    assert re.search(r'<button type="submit"[^>]*>Save</button>', response.text)


def test_admin_products_requires_login(client):
    """
    What we verify:
    - /admin/products is protected
    - anonymous user cannot access admin product list
    """

    response = client.get("/admin/products")

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin access denied"}
