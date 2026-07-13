from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from app.core.config import settings
from app.services.storage.r2_storage_service import (
    R2SignedUrlError,
    R2StorageService,
)


def configure_r2(monkeypatch):
    monkeypatch.setattr(settings, "R2_ACCOUNT_ID", "account-id")
    monkeypatch.setattr(settings, "R2_ACCESS_KEY_ID", "access-key")
    monkeypatch.setattr(settings, "R2_SECRET_ACCESS_KEY", "secret-key")
    monkeypatch.setattr(settings, "R2_BUCKET_NAME", "release-bucket")


def test_generate_signed_get_url_uses_configured_bucket_and_ttl(monkeypatch):
    configure_r2(monkeypatch)
    monkeypatch.setattr(settings, "DOWNLOAD_SIGNED_URL_TTL_SECONDS", 321)
    client = Mock()
    client.generate_presigned_url.return_value = "https://r2.example/signed"
    monkeypatch.setattr("app.services.storage.r2_storage_service.boto3.client", lambda *args, **kwargs: client)

    result = R2StorageService().generate_signed_get_url(
        storage_key="product-releases/smartbudget/1.0.zip"
    )

    assert result == "https://r2.example/signed"
    client.generate_presigned_url.assert_called_once_with(
        ClientMethod="get_object",
        Params={
            "Bucket": "release-bucket",
            "Key": "product-releases/smartbudget/1.0.zip",
        },
        ExpiresIn=321,
    )


def test_generate_signed_get_url_hides_provider_failure(monkeypatch):
    configure_r2(monkeypatch)
    client = Mock()
    client.generate_presigned_url.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "provider secret detail"}},
        "GetObject",
    )
    monkeypatch.setattr("app.services.storage.r2_storage_service.boto3.client", lambda *args, **kwargs: client)

    with pytest.raises(R2SignedUrlError) as exc_info:
        R2StorageService().generate_signed_get_url(storage_key="release.zip")

    assert "provider secret detail" not in str(exc_info.value)
