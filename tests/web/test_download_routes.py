from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models.download_entitlement import DownloadEntitlementStatus
from app.models.enums import PaymentStatus
from app.models.product import Product
from app.models.product_release import ProductRelease
from app.services.download_entitlement_service import create_download_entitlement
from app.services.sale_service import create_product_sale
from app.services.storage.r2_storage_service import R2SignedUrlError


def create_download(db_session):
    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-download-route-test",
        name="SmartBudget Route Edition",
        edition="Standard",
        archive_path="legacy/smartbudget.zip",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()
    release = ProductRelease(
        product_id=product.id,
        version="2.4.1",
        storage_provider="cloudflare_r2",
        storage_key="product-releases/smartbudget/2.4.1.zip",
        original_filename="SmartBudget_2.4.1.zip",
        file_size=2 * 1024 * 1024,
        sha256_hash="a" * 64,
        is_active=True,
        released_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    db_session.add(release)
    db_session.flush()
    sale = create_product_sale(
        db_session,
        product=product,
        product_release=release,
        customer_email="customer@example.com",
        amount=Decimal("39.00"),
        currency="EUR",
        payment_status=PaymentStatus.PAID,
    )
    db_session.flush()
    entitlement = create_download_entitlement(db_session, sale.items[0])
    db_session.commit()
    return entitlement, release


def test_download_get_renders_release_without_exposing_token_or_mutating(
    client,
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "DOWNLOAD_MAX_ATTEMPTS", 3)
    entitlement, release = create_download(db_session)
    token = entitlement.download_token

    response = client.get(f"/download/{token}")

    assert response.status_code == 200
    assert "SmartBudget Route Edition" in response.text
    assert release.version in response.text
    assert release.original_filename in response.text
    assert "2.0 MB" in response.text
    assert release.sha256_hash in response.text
    assert "01.07.2026" in response.text
    assert "DL-" in response.text
    assert entitlement.support_reference in response.text
    assert token not in response.text
    assert release.storage_key not in response.text
    db_session.expire_all()
    assert db_session.get(type(entitlement), entitlement.id).attempt_count == 0


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        ("Download link was not found.", "Ссылка для скачивания не найдена"),
        ("Download link has expired.", "Срок действия ссылки"),
        ("Download link has been cancelled.", "Доступ к скачиванию был отменён"),
        ("This download has already been completed.", "скачивание уже было завершено"),
        ("Download attempt limit has been reached.", "максимальное количество попыток"),
        ("Download release was not found.", "Приобретённый выпуск сейчас недоступен"),
    ],
)
def test_download_get_localizes_entitlement_errors(
    client,
    monkeypatch,
    detail,
    expected,
):
    def reject(*args, **kwargs):
        raise HTTPException(status_code=403, detail=detail)

    monkeypatch.setattr(
        "app.web.routes.get_valid_download_entitlement_by_token",
        reject,
    )

    response = client.get("/download/hidden-token?lang=ru")

    assert response.status_code == 403
    assert expected in response.text
    assert "hidden-token" not in response.text


def test_download_post_records_attempt_and_redirects_to_signed_url(
    client,
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "DOWNLOAD_MAX_ATTEMPTS", 3)
    entitlement, release = create_download(db_session)
    requested_keys = []

    class FakeStorage:
        def generate_signed_get_url(self, *, storage_key):
            requested_keys.append(storage_key)
            return "https://r2.example/temporary-download"

    monkeypatch.setattr("app.web.routes.R2StorageService", FakeStorage)

    response = client.post(
        f"/download/{entitlement.download_token}",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "https://r2.example/temporary-download"
    assert requested_keys == [release.storage_key]
    db_session.expire_all()
    refreshed = db_session.get(type(entitlement), entitlement.id)
    assert refreshed.attempt_count == 1
    assert refreshed.first_attempt_at is not None
    assert refreshed.last_attempt_at is not None
    assert refreshed.status == DownloadEntitlementStatus.AVAILABLE.value


def test_download_post_blocks_attempt_limit_without_generating_url(
    client,
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "DOWNLOAD_MAX_ATTEMPTS", 3)
    entitlement, _ = create_download(db_session)
    entitlement.attempt_count = 3
    db_session.commit()

    class UnexpectedStorage:
        def __init__(self):
            raise AssertionError("Storage must not be called")

    monkeypatch.setattr("app.web.routes.R2StorageService", UnexpectedStorage)

    response = client.post(f"/download/{entitlement.download_token}")

    assert response.status_code == 403
    assert "maximum number of download attempts" in response.text
    db_session.expire_all()
    assert db_session.get(type(entitlement), entitlement.id).attempt_count == 3


def test_download_post_storage_failure_is_localized_and_still_counts_attempt(
    client,
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "DOWNLOAD_MAX_ATTEMPTS", 3)
    entitlement, _ = create_download(db_session)

    class FailingStorage:
        def generate_signed_get_url(self, *, storage_key):
            raise R2SignedUrlError("provider detail must stay hidden")

    monkeypatch.setattr("app.web.routes.R2StorageService", FailingStorage)

    response = client.post(f"/download/{entitlement.download_token}?lang=ru")

    assert response.status_code == 503
    assert "Сервис скачивания временно недоступен" in response.text
    assert "provider detail" not in response.text
    db_session.expire_all()
    refreshed = db_session.get(type(entitlement), entitlement.id)
    assert refreshed.attempt_count == 1
    assert refreshed.status == DownloadEntitlementStatus.AVAILABLE.value
    assert entitlement.support_reference in response.text
    assert "message_type=purchase_or_download_issue" in response.text
    assert f"support_reference={entitlement.support_reference}" in response.text
    assert entitlement.download_token not in response.text
    assert "provider detail" not in response.text
    assert entitlement.release.storage_key not in response.text
