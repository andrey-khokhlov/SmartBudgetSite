from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def build_settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


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
