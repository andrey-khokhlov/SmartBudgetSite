from unittest.mock import Mock
from datetime import UTC, datetime

import pytest
from botocore.exceptions import ClientError

from app.core.config import settings
from app.services.storage.r2_storage_service import (
    R2StorageOperationError,
    R2SignedUrlError,
    R2StorageService,
    build_product_release_storage_key,
    is_managed_product_release_key,
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
    monkeypatch.setattr(
        "app.services.storage.r2_storage_service.boto3.client",
        lambda *args, **kwargs: client,
    )

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
            "ResponseCacheControl": "private, no-store, max-age=0",
            "ResponseExpires": datetime(1970, 1, 1, tzinfo=UTC),
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
    assert params["ResponseCacheControl"] == "private, no-store, max-age=0"
    assert params["ResponseExpires"] == datetime(1970, 1, 1, tzinfo=UTC)


def test_generate_signed_get_url_hides_provider_failure(monkeypatch):
    configure_r2(monkeypatch)
    client = Mock()
    client.generate_presigned_url.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "provider secret detail"}},
        "GetObject",
    )
    monkeypatch.setattr(
        "app.services.storage.r2_storage_service.boto3.client",
        lambda *args, **kwargs: client,
    )

    with pytest.raises(R2SignedUrlError) as exc_info:
        R2StorageService().generate_signed_get_url(
            storage_key="release.zip",
            download_filename="SmartBudget.zip",
        )

    assert "provider secret detail" not in str(exc_info.value)


def test_build_product_release_storage_key_is_opaque_and_managed(monkeypatch):
    monkeypatch.setattr(
        settings,
        "R2_PRODUCT_RELEASES_PREFIX",
        "product-releases",
    )

    first = build_product_release_storage_key(
        product_id=7,
        version="1.2",
        token="a" * 32,
    )
    second = build_product_release_storage_key(
        product_id=7,
        version="1.2",
        token="b" * 32,
    )

    assert first == f"product-releases/7/1.2/{'a' * 32}"
    assert second != first
    assert is_managed_product_release_key(first)
    assert "customer-file.zip" not in first


def test_upload_supplies_integrity_metadata(monkeypatch):
    configure_r2(monkeypatch)
    client = Mock()
    monkeypatch.setattr(
        "app.services.storage.r2_storage_service.boto3.client",
        lambda *args, **kwargs: client,
    )
    storage_key = f"product-releases/7/1.2/{'a' * 32}"
    file_obj = Mock()

    uploaded = R2StorageService().upload_product_release_file(
        storage_key=storage_key,
        file_obj=file_obj,
        file_size=123,
        sha256_hash="f" * 64,
    )

    assert uploaded.storage_key == storage_key
    file_obj.seek.assert_called_once_with(0)
    call = client.upload_fileobj.call_args
    assert call.kwargs["Key"] == storage_key
    assert call.kwargs["ExtraArgs"] == {
        "Metadata": {
            "sha256": "f" * 64,
            "file-size": "123",
        }
    }


def test_head_and_verify_release_object(monkeypatch):
    configure_r2(monkeypatch)
    client = Mock()
    client.head_object.return_value = {
        "ContentLength": 123,
        "Metadata": {"sha256": "f" * 64, "file-size": "123"},
        "LastModified": datetime(2026, 7, 1, tzinfo=UTC),
    }
    monkeypatch.setattr(
        "app.services.storage.r2_storage_service.boto3.client",
        lambda *args, **kwargs: client,
    )
    storage = R2StorageService()

    stored = storage.head_product_release_object(storage_key="historical/key.zip")

    assert stored is not None
    assert stored.content_length == 123
    assert stored.sha256_hash == "f" * 64
    assert storage.verify_product_release_object(
        storage_key="historical/key.zip",
        expected_file_size=123,
        expected_sha256_hash="f" * 64,
    )
    assert not storage.verify_product_release_object(
        storage_key="historical/key.zip",
        expected_file_size=124,
        expected_sha256_hash="f" * 64,
    )


def test_head_missing_object_returns_none(monkeypatch):
    configure_r2(monkeypatch)
    client = Mock()
    client.head_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
        "HeadObject",
    )
    monkeypatch.setattr(
        "app.services.storage.r2_storage_service.boto3.client",
        lambda *args, **kwargs: client,
    )

    assert R2StorageService().head_product_release_object(storage_key="missing") is None


def test_delete_hides_provider_failure(monkeypatch):
    configure_r2(monkeypatch)
    client = Mock()
    client.delete_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "provider secret detail"}},
        "DeleteObject",
    )
    monkeypatch.setattr(
        "app.services.storage.r2_storage_service.boto3.client",
        lambda *args, **kwargs: client,
    )

    with pytest.raises(R2StorageOperationError) as exc_info:
        R2StorageService().delete_product_release_object(storage_key="key")

    assert "provider secret detail" not in str(exc_info.value)


def test_list_product_release_objects_paginates(monkeypatch):
    configure_r2(monkeypatch)
    client = Mock()
    client.list_objects_v2.side_effect = [
        {
            "Contents": [
                {
                    "Key": "product-releases/1/1.0/one",
                    "Size": 10,
                    "LastModified": datetime(2026, 7, 1, tzinfo=UTC),
                }
            ],
            "IsTruncated": True,
            "NextContinuationToken": "next-page",
        },
        {
            "Contents": [
                {
                    "Key": "product-releases/1/1.0/two",
                    "Size": 20,
                    "LastModified": datetime(2026, 7, 2, tzinfo=UTC),
                }
            ],
            "IsTruncated": False,
        },
    ]
    monkeypatch.setattr(
        "app.services.storage.r2_storage_service.boto3.client",
        lambda *args, **kwargs: client,
    )

    objects = R2StorageService().list_product_release_objects()

    assert [item.storage_key for item in objects] == [
        "product-releases/1/1.0/one",
        "product-releases/1/1.0/two",
    ]
    assert client.list_objects_v2.call_args_list[1].kwargs["ContinuationToken"] == (
        "next-page"
    )
