from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import BinaryIO
from urllib.parse import quote
from uuid import uuid4

import certifi
import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, status

from app.core.config import settings

DEFAULT_DOWNLOAD_FILENAME = "download"
ASCII_FILENAME_UNSAFE_PATTERN = re.compile(r"[^A-Za-z0-9._ -]+")
PRIVATE_NO_STORE_CACHE_CONTROL = "private, no-store, max-age=0"
EXPIRED_RESPONSE_DATE = datetime(1970, 1, 1, tzinfo=UTC)
RELEASE_SHA256_METADATA_KEY = "sha256"
RELEASE_FILE_SIZE_METADATA_KEY = "file-size"
MANAGED_RELEASE_TOKEN_PATTERN = re.compile(r"^[0-9a-f]{32}$")
RELEASE_VERSION_PATH_PATTERN = re.compile(r"^\d+\.\d+$")


@dataclass(frozen=True)
class UploadedObject:
    storage_provider: str
    storage_key: str


@dataclass(frozen=True)
class StoredObject:
    storage_key: str
    content_length: int
    sha256_hash: str | None
    last_modified: datetime | None


class R2SignedUrlError(Exception):
    """Raised when R2 cannot issue a temporary download URL."""


class R2StorageOperationError(Exception):
    """Raised when a release-storage operation cannot be completed safely."""


def managed_product_release_prefix() -> str:
    prefix = settings.R2_PRODUCT_RELEASES_PREFIX.strip().strip("/")
    if (
        not prefix
        or "\\" in prefix
        or any(segment in {"", ".", ".."} for segment in prefix.split("/"))
    ):
        raise R2StorageOperationError("Product release storage is unavailable.")
    return prefix


def build_product_release_storage_key(
    *,
    product_id: int,
    version: str,
    token: str | None = None,
) -> str:
    if product_id <= 0 or not RELEASE_VERSION_PATH_PATTERN.fullmatch(version):
        raise ValueError("A valid product and release version are required")

    opaque_token = token or uuid4().hex
    if not MANAGED_RELEASE_TOKEN_PATTERN.fullmatch(opaque_token):
        raise ValueError("Release storage tokens must be 32 lowercase hex characters")

    return f"{managed_product_release_prefix()}/{product_id}/{version}/{opaque_token}"


def is_managed_product_release_key(storage_key: str) -> bool:
    prefix = re.escape(managed_product_release_prefix())
    return (
        re.fullmatch(
            rf"{prefix}/[1-9]\d*/\d+\.\d+/[0-9a-f]{{32}}",
            storage_key,
        )
        is not None
    )


def is_within_product_release_prefix(storage_key: str) -> bool:
    prefix = managed_product_release_prefix()
    return storage_key.startswith(f"{prefix}/")


class R2StorageService:
    """
    Cloudflare R2 storage adapter for product release files.
    """

    storage_provider = "cloudflare_r2"

    def __init__(self) -> None:
        self._validate_settings()

        endpoint_url = f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name="auto",
            verify=certifi.where(),
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 2, "mode": "standard"},
                connect_timeout=10,
                read_timeout=30,
                proxies={},
            ),
        )

    def upload_product_release_file(
        self,
        *,
        storage_key: str,
        file_obj: BinaryIO,
        file_size: int,
        sha256_hash: str,
    ) -> UploadedObject:
        if not is_managed_product_release_key(storage_key):
            raise ValueError("Release object key is outside the managed key format")

        transfer_config = TransferConfig(
            multipart_threshold=64 * 1024 * 1024,
            multipart_chunksize=64 * 1024 * 1024,
        )

        file_obj.seek(0)
        try:
            self.client.upload_fileobj(
                Fileobj=file_obj,
                Bucket=settings.R2_BUCKET_NAME,
                Key=storage_key,
                ExtraArgs={
                    "Metadata": {
                        RELEASE_SHA256_METADATA_KEY: sha256_hash,
                        RELEASE_FILE_SIZE_METADATA_KEY: str(file_size),
                    }
                },
                Config=transfer_config,
            )
        except (BotoCoreError, ClientError) as exc:
            raise R2StorageOperationError(
                "Product release storage is unavailable."
            ) from exc

        return UploadedObject(
            storage_provider=self.storage_provider,
            storage_key=storage_key,
        )

    def head_product_release_object(self, *, storage_key: str) -> StoredObject | None:
        try:
            response = self.client.head_object(
                Bucket=settings.R2_BUCKET_NAME,
                Key=storage_key,
            )
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            if error_code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise R2StorageOperationError(
                "Product release storage is unavailable."
            ) from exc
        except BotoCoreError as exc:
            raise R2StorageOperationError(
                "Product release storage is unavailable."
            ) from exc

        metadata = response.get("Metadata") or {}
        last_modified = response.get("LastModified")
        return StoredObject(
            storage_key=storage_key,
            content_length=int(response["ContentLength"]),
            sha256_hash=metadata.get(RELEASE_SHA256_METADATA_KEY),
            last_modified=last_modified,
        )

    def verify_product_release_object(
        self,
        *,
        storage_key: str,
        expected_file_size: int,
        expected_sha256_hash: str,
    ) -> bool:
        stored_object = self.head_product_release_object(storage_key=storage_key)
        return (
            stored_object is not None
            and stored_object.content_length == expected_file_size
            and stored_object.sha256_hash == expected_sha256_hash
        )

    def delete_product_release_object(self, *, storage_key: str) -> None:
        try:
            self.client.delete_object(
                Bucket=settings.R2_BUCKET_NAME,
                Key=storage_key,
            )
        except (BotoCoreError, ClientError) as exc:
            raise R2StorageOperationError(
                "Product release storage is unavailable."
            ) from exc

    def list_product_release_objects(self) -> list[StoredObject]:
        prefix = f"{managed_product_release_prefix()}/"
        continuation_token: str | None = None
        objects: list[StoredObject] = []

        while True:
            request = {
                "Bucket": settings.R2_BUCKET_NAME,
                "Prefix": prefix,
            }
            if continuation_token is not None:
                request["ContinuationToken"] = continuation_token

            try:
                response = self.client.list_objects_v2(**request)
            except (BotoCoreError, ClientError) as exc:
                raise R2StorageOperationError(
                    "Product release storage is unavailable."
                ) from exc

            objects.extend(
                StoredObject(
                    storage_key=item["Key"],
                    content_length=int(item["Size"]),
                    sha256_hash=None,
                    last_modified=item.get("LastModified"),
                )
                for item in response.get("Contents", [])
            )

            if not response.get("IsTruncated"):
                break

            continuation_token = response.get("NextContinuationToken")
            if not continuation_token:
                raise R2StorageOperationError(
                    "Product release storage pagination failed."
                )

        return objects

    def generate_signed_get_url(
        self,
        *,
        storage_key: str,
        download_filename: str,
    ) -> str:
        """Generate a short-lived GET-only URL without persisting it."""
        try:
            return self.client.generate_presigned_url(
                ClientMethod="get_object",
                Params={
                    "Bucket": settings.R2_BUCKET_NAME,
                    "Key": storage_key,
                    "ResponseContentDisposition": _build_content_disposition(
                        download_filename
                    ),
                    "ResponseCacheControl": PRIVATE_NO_STORE_CACHE_CONTROL,
                    "ResponseExpires": EXPIRED_RESPONSE_DATE,
                },
                ExpiresIn=settings.DOWNLOAD_SIGNED_URL_TTL_SECONDS,
            )
        except (BotoCoreError, ClientError) as exc:
            raise R2SignedUrlError("Could not generate a signed R2 URL.") from exc

    @staticmethod
    def _validate_settings() -> None:
        missing_settings = [
            name
            for name, value in {
                "R2_ACCOUNT_ID": settings.R2_ACCOUNT_ID,
                "R2_ACCESS_KEY_ID": settings.R2_ACCESS_KEY_ID,
                "R2_SECRET_ACCESS_KEY": settings.R2_SECRET_ACCESS_KEY,
                "R2_BUCKET_NAME": settings.R2_BUCKET_NAME,
            }.items()
            if not value
        ]

        if missing_settings:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "R2 storage is not configured. Missing settings: "
                    + ", ".join(missing_settings)
                ),
            )


def _build_content_disposition(filename: str) -> str:
    safe_filename = _sanitize_download_filename(filename)
    ascii_filename = _ascii_download_filename(safe_filename)
    encoded_filename = quote(safe_filename, safe="")
    return (
        f'attachment; filename="{ascii_filename}"; '
        f"filename*=UTF-8''{encoded_filename}"
    )


def _sanitize_download_filename(filename: str) -> str:
    without_controls = "".join(
        character
        for character in filename
        if not unicodedata.category(character).startswith("C")
    )
    basename = without_controls.replace("\\", "/").rsplit("/", 1)[-1]
    basename = basename.replace('"', "").strip(" .")
    if not basename:
        return DEFAULT_DOWNLOAD_FILENAME
    return basename


def _ascii_download_filename(filename: str) -> str:
    normalized = unicodedata.normalize("NFKD", filename)
    ascii_filename = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_filename = ASCII_FILENAME_UNSAFE_PATTERN.sub("_", ascii_filename)
    ascii_filename = ascii_filename.strip()
    if ascii_filename.startswith("."):
        ascii_filename = ""
    else:
        ascii_filename = ascii_filename.strip(" .")
    if ascii_filename:
        return ascii_filename

    extension = ""
    if "." in filename:
        candidate = filename.rsplit(".", 1)[-1]
        if candidate.isascii() and candidate.isalnum() and len(candidate) <= 16:
            extension = f".{candidate}"
    return f"{DEFAULT_DOWNLOAD_FILENAME}{extension}"
