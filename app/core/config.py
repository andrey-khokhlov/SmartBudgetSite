import os
import re
from datetime import date
from ipaddress import IPv4Address
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ENV_FILE allows switching environments (dev/prod/test)
# Default is ".env" if ENV_FILE is not explicitly set
ENV_FILE = os.getenv("ENV_FILE", ".env")


class Settings(BaseSettings):
    APP_NAME: str = "SmartBudget API"
    APP_ENV: Literal["dev", "test", "prod"] = "dev"
    APP_VERSION: str = "0.1.0"
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8000
    SMARTBUDGET_HOST: str = ""
    SMARTBUDGET_CADDY_PEER: IPv4Address | None = None

    BACKEND_CORS_ORIGINS: str = ""
    DATABASE_URL: str = ""

    POSTGRES_USER: str = ""
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""

    SECRET_KEY: str = ""
    UPLOAD_DIR: str = "uploads"
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_MAX_IDENTITIES: int = Field(default=10_000, gt=0)

    MAIL_FROM_EMAIL: str = ""
    MAIL_FROM_NAME: str = "SmartBudget"
    RESEND_API_KEY: str | None = None
    RESEND_WEBHOOK_SIGNING_SECRET: str | None = None
    PURCHASE_EMAIL_DELIVERY_ENABLED: bool = False
    PURCHASE_EMAIL_RECOVERY_PENDING_DELAY_MINUTES: int = Field(default=5, gt=0)
    PUBLIC_BASE_URL: str | None = None

    SELLER_ADDRESS_RU: str = Field(default="", repr=False)
    SELLER_ADDRESS_EN: str = Field(default="", repr=False)
    SELLER_CONTACT_PHONE: str = Field(default="", repr=False)
    REFUND_POLICY_PUBLICATION_DATE: date | None = None

    MAIL_SMTP_HOST: str = ""
    MAIL_SMTP_PORT: int = 587
    MAIL_SMTP_USER: str = ""
    MAIL_SMTP_PASSWORD: str = ""
    MAIL_SMTP_TLS: bool = True
    ADMIN_NOTIFICATION_EMAIL: str = ""

    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_CHAT_ID: str | None = None
    PURCHASE_ALERT_DELIVERY_ENABLED: bool = False
    REFUND_REQUEST_ALERT_DELIVERY_ENABLED: bool = False
    REFUND_REQUEST_REMINDER_DELIVERY_ENABLED: bool = False

    CALENDLY_CONSULTATION_URL: str | None = None  # Legacy environment compatibility.
    CALENDLY_CONSULTATION_EVENT_TYPE_URI: str | None = None
    CALENDLY_WEBHOOK_SIGNING_SECRET: str | None = None
    CALENDLY_PERSONAL_ACCESS_TOKEN: str | None = None
    CONSULTATION_CAPACITY_LIMIT: int = Field(default=4, gt=1)
    CONSULTATION_CAPACITY_WARNING_THRESHOLD: int = Field(default=3, gt=0)
    CONSULTATION_CAPACITY_ALERT_DELIVERY_ENABLED: bool = False

    BUNDLE_CHECKOUT_ENABLED: bool = False
    LAVA_TOP_API_KEY: str | None = None
    LAVA_TOP_WEBHOOK_SECRET: str | None = None
    LAVA_TOP_API_BASE_URL: str = "https://gate.lava.top"
    LAVA_TOP_RECOVERY_MAX_LOOKUPS: int = Field(default=20, gt=0)
    LAVA_TOP_RECOVERY_REQUEST_WINDOW_SECONDS: int = Field(default=120, gt=0, le=120)

    ADMIN_TOKEN: str = ""

    R2_ACCOUNT_ID: str | None = None
    R2_ACCESS_KEY_ID: str | None = None
    R2_SECRET_ACCESS_KEY: str | None = None
    R2_BUCKET_NAME: str | None = None
    R2_PRODUCT_RELEASES_PREFIX: str = "product-releases"
    PRODUCT_RELEASE_MAX_UPLOAD_BYTES: int = Field(
        default=50 * 1024 * 1024,
        gt=0,
    )

    DOWNLOAD_TOKEN_TTL_HOURS: int = 24
    DOWNLOAD_SIGNED_URL_TTL_SECONDS: int = 900
    DOWNLOAD_MAX_ATTEMPTS: int = 3

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="forbid",
    )

    @property
    def seller_information_available(self) -> bool:
        return all(
            value.strip()
            for value in (
                self.SELLER_ADDRESS_RU,
                self.SELLER_ADDRESS_EN,
                self.SELLER_CONTACT_PHONE,
            )
        )

    @property
    def refund_policy_available(self) -> bool:
        return (
            self.REFUND_POLICY_PUBLICATION_DATE is not None
            and self.seller_information_available
        )

    @field_validator("REFUND_POLICY_PUBLICATION_DATE", mode="before")
    @classmethod
    def parse_refund_policy_publication_date(cls, value: str | date | None) -> date | None:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            publication_date = date.fromisoformat(value)
            if publication_date.isoformat() != value:
                raise ValueError("Use YYYY-MM-DD for the refund policy publication date")
            return publication_date
        return value

    @model_validator(mode="after")
    def validate_consultation_capacity(self) -> "Settings":
        if self.CONSULTATION_CAPACITY_WARNING_THRESHOLD >= self.CONSULTATION_CAPACITY_LIMIT:
            raise ValueError(
                "CONSULTATION_CAPACITY_WARNING_THRESHOLD must be below "
                "CONSULTATION_CAPACITY_LIMIT"
            )
        return self

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if (
            self.LAVA_TOP_API_KEY
            and self.LAVA_TOP_WEBHOOK_SECRET
            and self.LAVA_TOP_API_KEY.strip() == self.LAVA_TOP_WEBHOOK_SECRET.strip()
        ):
            raise ValueError(
                "LAVA_TOP_WEBHOOK_SECRET must differ from LAVA_TOP_API_KEY"
            )

        if self.PURCHASE_EMAIL_DELIVERY_ENABLED:
            required_email_settings = {
                "RESEND_API_KEY": self.RESEND_API_KEY or "",
                "MAIL_FROM_EMAIL": self.MAIL_FROM_EMAIL,
                "MAIL_FROM_NAME": self.MAIL_FROM_NAME,
                "PUBLIC_BASE_URL": self.PUBLIC_BASE_URL or "",
            }
            for field_name, value in required_email_settings.items():
                if not value.strip():
                    raise ValueError(
                        f"{field_name} must be non-empty when purchase email "
                        "delivery is enabled"
                    )

            parsed_base_url = urlsplit(required_email_settings["PUBLIC_BASE_URL"])
            if (
                parsed_base_url.scheme not in {"http", "https"}
                or not parsed_base_url.netloc
                or parsed_base_url.query
                or parsed_base_url.fragment
            ):
                raise ValueError(
                    "PUBLIC_BASE_URL must be an absolute HTTP(S) URL without "
                    "a query string or fragment"
                )
            if self.APP_ENV == "prod" and parsed_base_url.scheme != "https":
                raise ValueError(
                    "PUBLIC_BASE_URL must use HTTPS when purchase email delivery "
                    "is enabled in production"
                )
            self.PUBLIC_BASE_URL = required_email_settings["PUBLIC_BASE_URL"].rstrip(
                "/"
            )

        if self.APP_ENV != "prod":
            return self

        for field_name in ("ADMIN_TOKEN", "SECRET_KEY"):
            if not getattr(self, field_name).strip():
                raise ValueError(
                    f"{field_name} must be non-empty when APP_ENV is 'prod'"
                )

        if not self.RATE_LIMIT_ENABLED:
            raise ValueError("RATE_LIMIT_ENABLED must be true when APP_ENV is 'prod'")

        if self.LAVA_TOP_API_KEY and not (self.LAVA_TOP_WEBHOOK_SECRET or "").strip():
            raise ValueError(
                "LAVA_TOP_WEBHOOK_SECRET must be non-empty when Lava.top "
                "checkout is enabled in production"
            )

        return self

    @model_validator(mode="after")
    def validate_production_host(self) -> "Settings":
        if self.APP_ENV != "prod":
            return self

        hostname = self.SMARTBUDGET_HOST.lower()
        label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
        if len(hostname) > 253 or not re.fullmatch(rf"{label}(?:\.{label})*", hostname):
            raise ValueError(
                "SMARTBUDGET_HOST must be a bare DNS hostname in production"
            )
        self.SMARTBUDGET_HOST = hostname
        return self


settings = Settings()
