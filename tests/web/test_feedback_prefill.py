from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.download_entitlement import (
    DownloadEntitlement,
    DownloadEntitlementStatus,
)
from app.models.enums import PaymentStatus, SaleItemType
from app.models.product import Product
from app.models.product_release import ProductRelease
from app.models.sale import Sale
from app.models.sale_item import SaleItem


PRODUCT_ID_SENTINEL = 910001
RELEASE_ID_SENTINEL = 910002
SALE_ID_SENTINEL = 910003
SALE_ITEM_ID_SENTINEL = 910004
ENTITLEMENT_ID_SENTINEL = 910005
DOWNLOAD_TOKEN_SENTINEL = "download-token-must-never-render"
STORAGE_KEY_SENTINEL = "storage-key-must-never-render"
SIGNED_URL_SENTINEL = "https://signed.example/signed-url-must-never-render"
PAYMENT_PROVIDER_SENTINEL = "payment-provider-must-never-render"
PAYMENT_ID_SENTINEL = "payment-id-must-never-render"


def create_prefill_download(db_session):
    product = Product(
        id=PRODUCT_ID_SENTINEL,
        family_slug="smartbudget",
        slug="smartbudget-feedback-prefill-test",
        name="SmartBudget Prefill",
        edition="Standard",
        archive_path=SIGNED_URL_SENTINEL,
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()
    release = ProductRelease(
        id=RELEASE_ID_SENTINEL,
        product_id=product.id,
        version="4.2.0",
        storage_provider="cloudflare_r2",
        storage_key=STORAGE_KEY_SENTINEL,
        original_filename="SmartBudget_4.2.0.zip",
        is_active=True,
    )
    db_session.add(release)
    db_session.flush()
    sale = Sale(
        id=SALE_ID_SENTINEL,
        product_id=product.id,
        customer_email="prefill-customer@example.com",
        amount=Decimal("49.00"),
        currency="EUR",
        payment_provider=PAYMENT_PROVIDER_SENTINEL,
        payment_status=PaymentStatus.PAID,
        external_payment_id=PAYMENT_ID_SENTINEL,
        created_at=datetime(2026, 7, 18, tzinfo=UTC),
    )
    db_session.add(sale)
    db_session.flush()
    sale_item = SaleItem(
        id=SALE_ITEM_ID_SENTINEL,
        sale_id=sale.id,
        item_type=SaleItemType.PRODUCT,
        product_id=product.id,
        product_release_id=release.id,
        item_name="SmartBudget Prefill Standard",
        currency_code="EUR",
        amount=Decimal("49.00"),
        quantity=1,
    )
    db_session.add(sale_item)
    db_session.flush()
    entitlement = DownloadEntitlement(
        id=ENTITLEMENT_ID_SENTINEL,
        sale_item_id=sale_item.id,
        release_id=release.id,
        download_token=DOWNLOAD_TOKEN_SENTINEL,
        support_reference="DL-ABCDEFGH",
        status=DownloadEntitlementStatus.AVAILABLE.value,
        expires_at=datetime.now(UTC) + timedelta(hours=12),
        attempt_count=0,
    )
    db_session.add(entitlement)
    db_session.commit()
    return entitlement, release, sale


@pytest.mark.parametrize(
    (
        "lang",
        "expected_type",
        "expected_subject",
        "expected_intro",
        "expected_date",
    ),
    [
        (
            "en",
            "Purchase or download issue",
            "Help with downloading SmartBudget Prefill (Standard)",
            "I need help with purchasing or downloading SmartBudget Prefill (Standard).",
            "Purchase date: 2026-07-18",
        ),
        (
            "ru",
            "Проблема с покупкой или скачиванием",
            "Помощь со скачиванием SmartBudget Prefill (Standard)",
            "Мне нужна помощь с покупкой или скачиванием SmartBudget Prefill (Standard).",
            "Дата покупки: 18.07.2026",
        ),
    ],
)
def test_feedback_get_prefills_existing_download_support_context(
    client,
    db_session,
    lang,
    expected_type,
    expected_subject,
    expected_intro,
    expected_date,
):
    entitlement, _, _ = create_prefill_download(db_session)

    response = client.get(
        "/feedback",
        params={
            "lang": lang,
            "message_type": "purchase_or_download_issue",
            "support_reference": entitlement.support_reference,
        },
    )

    assert response.status_code == 200
    assert expected_type in response.text
    assert 'value="purchase_or_download_issue" selected' in response.text
    assert 'value="prefill-customer@example.com"' in response.text
    assert f'value="{entitlement.support_reference}"' in response.text
    assert 'name="support_reference"' in response.text
    assert "readonly" in response.text
    assert expected_subject in response.text
    assert expected_intro in response.text
    assert "SmartBudget Prefill (Standard)" in response.text
    assert "4.2.0" in response.text
    assert expected_date in response.text


@pytest.mark.parametrize(
    "support_reference",
    [
        "DL-JKMNPQRS",
        "DL-ABCD0O1I",
        "PAY-ABCDEFGH",
    ],
)
def test_feedback_get_safely_ignores_unknown_malformed_or_unsupported_reference(
    client,
    db_session,
    support_reference,
):
    create_prefill_download(db_session)

    response = client.get(
        "/feedback",
        params={
            "message_type": "purchase_or_download_issue",
            "support_reference": support_reference,
        },
    )

    assert response.status_code == 200
    assert 'value="purchase_or_download_issue" selected' in response.text
    assert "prefill-customer@example.com" not in response.text
    assert "SmartBudget Prefill" not in response.text
    assert support_reference not in response.text
    assert 'name="support_reference"' not in response.text
    assert 'id="email" name="email" value=""' in response.text


def test_feedback_get_without_reference_preserves_normal_form(client):
    response = client.get("/feedback")

    assert response.status_code == 200
    assert 'value="purchase_or_download_issue" selected' not in response.text
    assert 'name="support_reference"' not in response.text
    assert 'id="email" name="email" value=""' in response.text
    assert (
        'id="subject" name="subject" maxlength="200" required value=""' in response.text
    )
    assert (
        'id="message" name="message" required maxlength="2000"></textarea>'
        in response.text
    )


def test_feedback_prefill_render_does_not_expose_secrets_or_internal_ids(
    client,
    db_session,
):
    entitlement, release, sale = create_prefill_download(db_session)

    response = client.get(
        "/feedback",
        params={
            "message_type": "purchase_or_download_issue",
            "support_reference": entitlement.support_reference,
        },
    )

    assert response.status_code == 200
    assert DOWNLOAD_TOKEN_SENTINEL not in response.text
    assert STORAGE_KEY_SENTINEL not in response.text
    assert SIGNED_URL_SENTINEL not in response.text
    assert PAYMENT_PROVIDER_SENTINEL not in response.text
    assert PAYMENT_ID_SENTINEL not in response.text
    assert str(PRODUCT_ID_SENTINEL) not in response.text
    assert str(RELEASE_ID_SENTINEL) not in response.text
    assert str(SALE_ID_SENTINEL) not in response.text
    assert str(SALE_ITEM_ID_SENTINEL) not in response.text
    assert str(ENTITLEMENT_ID_SENTINEL) not in response.text
    assert "sale_id" not in response.text
    assert "entitlement_id" not in response.text


def test_feedback_get_ignores_invalid_prefill_values(client):
    response = client.get(
        "/feedback",
        params={
            "message_type": "<script>alert(1)</script>",
            "support_reference": "/download/private-token",
        },
    )

    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text
    assert "/download/private-token" not in response.text
    assert 'name="support_reference"' not in response.text


def test_feedback_form_uses_one_email_field_for_private_feedback(client):
    response = client.get("/feedback?message_type=purchase_or_download_issue")

    assert response.status_code == 200
    assert 'id="email" name="email"' in response.text
    assert 'name="contact_email"' not in response.text
