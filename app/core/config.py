import os
from typing import Literal

from pydantic import Field, model_validator
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
    MAIL_SMTP_HOST: str = ""
    MAIL_SMTP_PORT: int = 587
    MAIL_SMTP_USER: str = ""
    MAIL_SMTP_PASSWORD: str = ""
    MAIL_SMTP_TLS: bool = True
    ADMIN_NOTIFICATION_EMAIL: str = ""

    CALENDLY_CONSULTATION_URL: str | None = None
    CALENDLY_WEBHOOK_SIGNING_SECRET: str | None = None
    CALENDLY_PERSONAL_ACCESS_TOKEN: str | None = None

    LAVA_TOP_API_KEY: str | None = None
    LAVA_TOP_WEBHOOK_SECRET: str | None = None
    LAVA_TOP_API_BASE_URL: str = "https://gate.lava.top"

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

    DOWNLOAD_TOKEN_TTL_HOURS: int = 12
    DOWNLOAD_SIGNED_URL_TTL_SECONDS: int = 900
    DOWNLOAD_MAX_ATTEMPTS: int = 3

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="forbid",
    )

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


settings = Settings()
