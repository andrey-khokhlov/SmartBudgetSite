from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import BinaryIO
from urllib.parse import quote

import certifi
import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, status

from app.core.config import settings

DEFAULT_DOWNLOAD_FILENAME = "download"
ASCII_FILENAME_UNSAFE_PATTERN = re.compile(r"[^A-Za-z0-9._ -]+")


@dataclass(frozen=True)
class UploadedObject:
    storage_provider: str
    storage_key: str


class R2SignedUrlError(Exception):
    """Raised when R2 cannot issue a temporary download URL."""


class R2StorageService:
    """
    Cloudflare R2 storage adapter for product release files.
    """

    storage_provider = "cloudflare_r2"

    def __init__(self) -> None:
        self._validate_settings()

        endpoint_url = (
            f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
        )

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
        product_slug: str,
        version: str,
        filename: str,
        file_obj: BinaryIO,
    ) -> UploadedObject:
        storage_key = (
            f"{settings.R2_PRODUCT_RELEASES_PREFIX}/"
            f"{product_slug}/"
            f"{version}/"
            f"{filename}"
        )

        transfer_config = TransferConfig(
            multipart_threshold=64 * 1024 * 1024,
            multipart_chunksize=64 * 1024 * 1024,
        )

        self.client.upload_fileobj(
            Fileobj=file_obj,
            Bucket=settings.R2_BUCKET_NAME,
            Key=storage_key,
            Config=transfer_config,
        )

        return UploadedObject(
            storage_provider=self.storage_provider,
            storage_key=storage_key,
        )

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
