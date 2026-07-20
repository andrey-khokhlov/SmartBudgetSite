import re
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.i18n import COOKIE_NAME
from app.models.product import Product
from app.models.product_price import ProductPrice


def _get_document_lang(response) -> str:
    match = re.search(r'<html\s+lang="([^"]*)"', response.text)
    assert match is not None
    return match.group(1)


@pytest.mark.parametrize(
    ("requested_lang", "expected_lang"),
    [
        ("en", "en"),
        ("ru", "ru"),
        ("RU", "ru"),
    ],
)
def test_public_document_declares_resolved_query_language(
    client: TestClient,
    requested_lang: str,
    expected_lang: str,
) -> None:
    response = client.get("/", params={"lang": requested_lang})

    assert response.status_code == 200
    assert _get_document_lang(response) == expected_lang


def test_public_document_uses_cookie_when_query_language_is_unsupported(
    client: TestClient,
) -> None:
    client.cookies.set(COOKIE_NAME, "ru")

    response = client.get("/faq", params={"lang": "de"})

    assert response.status_code == 200
    assert _get_document_lang(response) == "ru"


def test_valid_query_language_takes_precedence_over_valid_cookie(
    client: TestClient,
) -> None:
    client.cookies.set(COOKIE_NAME, "ru")

    response = client.get("/", params={"lang": "en"})

    assert response.status_code == 200
    assert _get_document_lang(response) == "en"


def test_invalid_language_input_is_not_rendered_into_document_attribute(
    client: TestClient,
) -> None:
    invalid_lang = 'ru"><script>alert(1)</script>'

    response = client.get("/", params={"lang": invalid_lang})

    assert response.status_code == 200
    assert _get_document_lang(response) == "en"
    assert invalid_lang not in response.text


def test_admin_login_declares_english_document_language(
    client: TestClient,
) -> None:
    response = client.get("/admin/login", params={"lang": "ru"})

    assert response.status_code == 200
    assert _get_document_lang(response) == "en"


def test_direct_admin_template_response_declares_english_document_language(
    auth_client: TestClient,
) -> None:
    response = auth_client.get("/admin/products", params={"lang": "ru"})

    assert response.status_code == 200
    assert _get_document_lang(response) == "en"


def test_direct_public_template_response_declares_resolved_language(
    client: TestClient,
    db_session,
) -> None:
    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-ru-standard-document-language-test",
        name="SmartBudget",
        edition="Standard",
        archive_path="",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()
    db_session.add(
        ProductPrice(
            product_id=product.id,
            currency_code="RUB",
            amount=Decimal("1490.00"),
            is_active=True,
        )
    )
    db_session.commit()

    response = client.get("/products/smartbudget/buy", params={"lang": "ru"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert _get_document_lang(response) == "ru"


def test_localized_download_error_declares_resolved_document_language(
    client: TestClient,
) -> None:
    response = client.get("/download/missing-token", params={"lang": "ru"})

    assert response.status_code == 404
    assert _get_document_lang(response) == "ru"
