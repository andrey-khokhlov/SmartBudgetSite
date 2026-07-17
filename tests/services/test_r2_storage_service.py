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
        storage_key="product-releases/smartbudget/1.0.zip",
        download_filename="SmartBudget 1.0.zip",
    )

    assert result == "https://r2.example/signed"
    client.generate_presigned_url.assert_called_once_with(
        ClientMethod="get_object",
        Params={
            "Bucket": "release-bucket",
            "Key": "product-releases/smartbudget/1.0.zip",
            "ResponseContentDisposition": (
                'attachment; filename="SmartBudget 1.0.zip"; '
                "filename*=UTF-8''SmartBudget%201.0.zip"
            ),
        },
        ExpiresIn=321,
    )


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        (
            "SmartBudget.zip",
            'attachment; filename="SmartBudget.zip"; '
            "filename*=UTF-8''SmartBudget.zip",
        ),
        (
            "Бюджет.xlsx",
            'attachment; filename="download.xlsx"; '
            "filename*=UTF-8''%D0%91%D1%8E%D0%B4%D0%B6%D0%B5%D1%82.xlsx",
        ),
        (
            '../private\\exports\\unsafe\r\n"report".zip',
            'attachment; filename="unsafereport.zip"; '
            "filename*=UTF-8''unsafereport.zip",
        ),
        (
            '../\r\n"\\.',
            "attachment; filename=\"download\"; filename*=UTF-8''download",
        ),
    ],
)
def test_generate_signed_get_url_builds_safe_content_disposition(
    monkeypatch,
    filename,
    expected,
):
    configure_r2(monkeypatch)
    client = Mock()
    client.generate_presigned_url.return_value = "https://r2.example/signed"
    monkeypatch.setattr(
        "app.services.storage.r2_storage_service.boto3.client",
        lambda *args, **kwargs: client,
    )

    R2StorageService().generate_signed_get_url(
        storage_key="release.zip",
        download_filename=filename,
    )

    params = client.generate_presigned_url.call_args.kwargs["Params"]
    assert params["ResponseContentDisposition"] == expected


def test_generate_signed_get_url_hides_provider_failure(monkeypatch):
    configure_r2(monkeypatch)
    client = Mock()
    client.generate_presigned_url.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "provider secret detail"}},
        "GetObject",
    )
    monkeypatch.setattr("app.services.storage.r2_storage_service.boto3.client", lambda *args, **kwargs: client)

    with pytest.raises(R2SignedUrlError) as exc_info:
        R2StorageService().generate_signed_get_url(
            storage_key="release.zip",
            download_filename="SmartBudget.zip",
        )

    assert "provider secret detail" not in str(exc_info.value)
