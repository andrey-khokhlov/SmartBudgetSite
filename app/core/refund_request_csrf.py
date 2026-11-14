
import hashlib
import hmac
import re

from app.core.config import settings

CSRF_COOKIE_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
CSRF_TOKEN_PATTERN = re.compile(r"[0-9a-f]{64}")
CSRF_SIGNATURE_PATTERN = re.compile(r"[0-9a-f]{64}")


def create_csrf_cookie_value(cookie_id: str, token: str) -> str:
    if not CSRF_COOKIE_ID_PATTERN.fullmatch(cookie_id):
        raise ValueError("Invalid CSRF cookie ID.")

    if not CSRF_TOKEN_PATTERN.fullmatch(token):
        raise ValueError("Invalid CSRF token.")

    secret = settings.SECRET_KEY.strip()
    if not secret:
        raise RuntimeError("SECRET_KEY must be configured for CSRF protection.")

    payload = f"refund-request-csrf:v1:{cookie_id}:{token}".encode("ascii")

    signature = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    return f"{token}.{signature}"


def verify_csrf_token(
    cookie_id: str,
    token: str,
    cookie_value: str | None,
) -> bool:
    if not cookie_value:
        return False

    if not CSRF_COOKIE_ID_PATTERN.fullmatch(cookie_id):
        return False

    if not CSRF_TOKEN_PATTERN.fullmatch(token):
        return False

    try:
        cookie_token, signature = cookie_value.split(".", 1)
    except ValueError:
        return False

    if not CSRF_TOKEN_PATTERN.fullmatch(cookie_token):
        return False

    if not CSRF_SIGNATURE_PATTERN.fullmatch(signature):
        return False

    expected_value = create_csrf_cookie_value(cookie_id, cookie_token)
    expected_signature = expected_value.split(".", 1)[1]

    return (
        hmac.compare_digest(token, cookie_token)
        and hmac.compare_digest(signature, expected_signature)
    )
