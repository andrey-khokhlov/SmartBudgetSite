from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def build_settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_seller_information_availability_from_environment(monkeypatch):
    fields = ("SELLER_ADDRESS_RU", "SELLER_ADDRESS_EN", "SELLER_CONTACT_PHONE")
    for field in fields:
        monkeypatch.delenv(field, raising=False)
    assert not build_settings().seller_information_available

    monkeypatch.setenv("SELLER_ADDRESS_RU", "Вымышленный адрес")
    monkeypatch.setenv("SELLER_ADDRESS_EN", "Fictional address")
    assert not build_settings().seller_information_available
    monkeypatch.setenv("SELLER_CONTACT_PHONE", "   ")
    assert not build_settings().seller_information_available
    monkeypatch.setenv("SELLER_CONTACT_PHONE", "+1 202-555-0147")

    configured = build_settings()
    assert configured.seller_information_available
    assert configured.SELLER_ADDRESS_RU == "Вымышленный адрес"
    assert configured.SELLER_ADDRESS_EN == "Fictional address"
    assert configured.SELLER_CONTACT_PHONE == "+1 202-555-0147"


def test_consultation_capacity_defaults_and_overrides(monkeypatch):
    config = build_settings()
    assert config.CONSULTATION_CAPACITY_LIMIT == 4
    assert config.CONSULTATION_CAPACITY_WARNING_THRESHOLD == 3
    assert not config.CONSULTATION_CAPACITY_ALERT_DELIVERY_ENABLED
    monkeypatch.setenv("CONSULTATION_CAPACITY_LIMIT", "8")
    monkeypatch.setenv("CONSULTATION_CAPACITY_WARNING_THRESHOLD", "6")
    config = build_settings()
    assert config.CONSULTATION_CAPACITY_LIMIT == 8
    assert config.CONSULTATION_CAPACITY_WARNING_THRESHOLD == 6


@pytest.mark.parametrize(("limit", "warning"), [(4, 0), (4, 4), (4, 5), (1, 1)])
def test_consultation_capacity_rejects_invalid_thresholds(limit, warning):
    with pytest.raises(ValidationError):
        build_settings(
            CONSULTATION_CAPACITY_LIMIT=limit,
            CONSULTATION_CAPACITY_WARNING_THRESHOLD=warning,
        )


@pytest.mark.parametrize("app_env", ["dev", "test", "prod"])
def test_app_env_accepts_supported_values(app_env: str) -> None:
    configured_settings = build_settings(
        APP_ENV=app_env,
        ADMIN_TOKEN="production-admin-token",
        SECRET_KEY="production-secret-key",
        SMARTBUDGET_HOST="smartbudget.example.test",
    )

    assert configured_settings.APP_ENV == app_env


@pytest.mark.parametrize(
    "app_env",
    ["production", "development", "prd", "", "unknown-environment"],
)
def test_app_env_rejects_unsupported_values(app_env: str) -> None:
    with pytest.raises(ValidationError):
        build_settings(APP_ENV=app_env)


@pytest.mark.parametrize("invalid_value", ["", "   \t"])
def test_production_rejects_invalid_admin_token(invalid_value: str) -> None:
    with pytest.raises(ValidationError, match="ADMIN_TOKEN must be non-empty"):
        build_settings(
            APP_ENV="prod",
            ADMIN_TOKEN=invalid_value,
            SECRET_KEY="production-secret-key",
        )


@pytest.mark.parametrize("invalid_value", ["", "   \t"])
def test_production_rejects_invalid_secret_key(invalid_value: str) -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY must be non-empty"):
        build_settings(
            APP_ENV="prod",
            ADMIN_TOKEN="production-admin-token",
            SECRET_KEY=invalid_value,
        )


def test_production_accepts_non_empty_security_secrets() -> None:
    configured_settings = build_settings(
        APP_ENV="prod",
        ADMIN_TOKEN="production-admin-token",
        SECRET_KEY="production-secret-key",
        SMARTBUDGET_HOST="smartbudget.example.test",
    )

    assert configured_settings.ADMIN_TOKEN == "production-admin-token"
    assert configured_settings.SECRET_KEY == "production-secret-key"


def test_production_rejects_missing_admin_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)

    with pytest.raises(ValidationError, match="ADMIN_TOKEN must be non-empty"):
        build_settings(
            APP_ENV="prod",
            SECRET_KEY="production-secret-key",
        )


def test_production_rejects_missing_secret_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(ValidationError, match="SECRET_KEY must be non-empty"):
        build_settings(
            APP_ENV="prod",
            ADMIN_TOKEN="production-admin-token",
        )


@pytest.mark.parametrize(
    "hostname", ["", "*", "*.example.test", "https://example.test", "example.test:443"]
)
def test_production_requires_a_bare_dns_hostname(hostname: str) -> None:
    with pytest.raises(ValidationError, match="SMARTBUDGET_HOST must be a bare DNS"):
        build_settings(
            APP_ENV="prod",
            ADMIN_TOKEN="production-admin-token",
            SECRET_KEY="production-secret-key",
            SMARTBUDGET_HOST=hostname,
        )


def test_development_preserves_empty_security_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)

    configured_settings = build_settings(APP_ENV="dev")

    assert configured_settings.ADMIN_TOKEN == ""
    assert configured_settings.SECRET_KEY == ""


def test_test_environment_preserves_empty_security_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)

    configured_settings = build_settings(APP_ENV="test")

    assert configured_settings.ADMIN_TOKEN == ""
    assert configured_settings.SECRET_KEY == ""


def test_release_upload_limit_has_safe_default() -> None:
    configured_settings = build_settings()

    assert configured_settings.PRODUCT_RELEASE_MAX_UPLOAD_BYTES == 52_428_800


@pytest.mark.parametrize("invalid_limit", [0, -1])
def test_release_upload_limit_must_be_positive(invalid_limit: int) -> None:
    with pytest.raises(ValidationError, match="greater than 0"):
        build_settings(PRODUCT_RELEASE_MAX_UPLOAD_BYTES=invalid_limit)


def test_rate_limit_configuration_has_safe_defaults() -> None:
    configured_settings = build_settings()

    assert configured_settings.RATE_LIMIT_ENABLED is True
    assert configured_settings.RATE_LIMIT_MAX_IDENTITIES == 10_000


def test_lava_top_configuration_has_safe_defaults() -> None:
    configured_settings = build_settings()

    assert configured_settings.LAVA_TOP_API_KEY is None
    assert configured_settings.LAVA_TOP_WEBHOOK_SECRET is None
    assert configured_settings.LAVA_TOP_API_BASE_URL == "https://gate.lava.top"


def test_purchase_email_delivery_has_safe_defaults() -> None:
    configured_settings = build_settings()

    assert configured_settings.PURCHASE_EMAIL_DELIVERY_ENABLED is False
    assert configured_settings.PUBLIC_BASE_URL is None


def test_enabled_purchase_email_requires_complete_configuration() -> None:
    with pytest.raises(ValidationError, match="RESEND_API_KEY must be non-empty"):
        build_settings(PURCHASE_EMAIL_DELIVERY_ENABLED=True)


def test_enabled_purchase_email_accepts_absolute_public_base_url() -> None:
    configured_settings = build_settings(
        PURCHASE_EMAIL_DELIVERY_ENABLED=True,
        RESEND_API_KEY="resend-key",
        MAIL_FROM_EMAIL="support@example.test",
        MAIL_FROM_NAME="SmartBudget",
        PUBLIC_BASE_URL="https://app.example.test/",
    )

    assert configured_settings.PUBLIC_BASE_URL == "https://app.example.test"


@pytest.mark.parametrize(
    "public_base_url",
    ["localhost:8800", "/relative", "https://app.example.test/?token=secret"],
)
def test_enabled_purchase_email_rejects_unsafe_public_base_url(
    public_base_url: str,
) -> None:
    with pytest.raises(ValidationError, match="PUBLIC_BASE_URL must be"):
        build_settings(
            PURCHASE_EMAIL_DELIVERY_ENABLED=True,
            RESEND_API_KEY="resend-key",
            MAIL_FROM_EMAIL="support@example.test",
            MAIL_FROM_NAME="SmartBudget",
            PUBLIC_BASE_URL=public_base_url,
        )


def test_production_purchase_email_requires_https_public_base_url() -> None:
    with pytest.raises(ValidationError, match="must use HTTPS"):
        build_settings(
            APP_ENV="prod",
            ADMIN_TOKEN="production-admin-token",
            SECRET_KEY="production-secret-key",
            PURCHASE_EMAIL_DELIVERY_ENABLED=True,
            RESEND_API_KEY="resend-key",
            MAIL_FROM_EMAIL="support@example.test",
            MAIL_FROM_NAME="SmartBudget",
            PUBLIC_BASE_URL="http://app.example.test",
        )


def test_production_lava_checkout_requires_separate_webhook_secret() -> None:
    with pytest.raises(
        ValidationError,
        match="LAVA_TOP_WEBHOOK_SECRET must be non-empty",
    ):
        build_settings(
            APP_ENV="prod",
            ADMIN_TOKEN="production-admin-token",
            SECRET_KEY="production-secret-key",
            LAVA_TOP_API_KEY="outbound-key",
        )


def test_production_lava_checkout_accepts_webhook_secret() -> None:
    configured_settings = build_settings(
        APP_ENV="prod",
        ADMIN_TOKEN="production-admin-token",
        SECRET_KEY="production-secret-key",
        LAVA_TOP_API_KEY="outbound-key",
        LAVA_TOP_WEBHOOK_SECRET="different-inbound-key",
        SMARTBUDGET_HOST="smartbudget.example.test",
    )

    assert configured_settings.LAVA_TOP_WEBHOOK_SECRET == "different-inbound-key"


def test_lava_top_inbound_and_outbound_secrets_must_differ() -> None:
    with pytest.raises(
        ValidationError,
        match="LAVA_TOP_WEBHOOK_SECRET must differ",
    ):
        build_settings(
            LAVA_TOP_API_KEY="same-key",
            LAVA_TOP_WEBHOOK_SECRET="same-key",
        )


@pytest.mark.parametrize("invalid_capacity", [0, -1])
def test_rate_limit_capacity_must_be_positive(invalid_capacity: int) -> None:
    with pytest.raises(ValidationError, match="greater than 0"):
        build_settings(RATE_LIMIT_MAX_IDENTITIES=invalid_capacity)


def test_production_rejects_disabled_rate_limiting() -> None:
    with pytest.raises(
        ValidationError,
        match="RATE_LIMIT_ENABLED must be true",
    ):
        build_settings(
            APP_ENV="prod",
            ADMIN_TOKEN="production-admin-token",
            SECRET_KEY="production-secret-key",
            RATE_LIMIT_ENABLED=False,
        )
