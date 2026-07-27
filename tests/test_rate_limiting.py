from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from starlette.requests import Request

from app.core.config import settings
from app.core.rate_limiting import (
    RATE_LIMIT_MESSAGE,
    RateLimitExceeded,
    RateLimitRule,
    RateLimiterUnavailable,
    RollingWindowRateLimiter,
    canonicalize_client_host,
    enforce_calendly_verified_limits,
    keyed_identity,
)
from app.dependencies import ADMIN_COOKIE_NAME
from app.main import app

CAPABILITY_RESPONSE_HEADERS = {
    "cache-control": "private, no-store, max-age=0",
    "pragma": "no-cache",
    "expires": "0",
    "referrer-policy": "no-referrer",
}


class FakeClock:
    def __init__(self, initial: float = 1000.0) -> None:
        self.value = initial

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def rule(
    *,
    policy: str = "test_policy",
    limit: int = 2,
    window: int = 60,
    identity: str = "identity-a",
    kind: str = "client_ip",
) -> RateLimitRule:
    return RateLimitRule(
        policy_name=policy,
        limit=limit,
        window_seconds=window,
        identity_kind=kind,
        identity_key=identity,
    )


@pytest.fixture
def controlled_limiter(monkeypatch: pytest.MonkeyPatch):
    clock = FakeClock()
    limiter = RollingWindowRateLimiter(max_identities=100, clock=clock)
    monkeypatch.setattr(app.state, "rate_limiter", limiter)
    return limiter, clock


def assert_capability_headers(response) -> None:
    for name, expected in CAPABILITY_RESPONSE_HEADERS.items():
        assert response.headers[name] == expected


def test_rolling_window_retry_after_and_expiry_use_injected_monotonic_clock():
    clock = FakeClock()
    limiter = RollingWindowRateLimiter(max_identities=10, clock=clock)
    request_rule = rule()

    assert limiter.check([request_rule]).allowed
    clock.advance(10.2)
    assert limiter.check([request_rule]).allowed

    denied = limiter.check([request_rule])
    assert denied.allowed is False
    assert denied.retry_after == 50
    assert denied.should_log is True

    repeated = limiter.check([request_rule])
    assert repeated.retry_after == 50
    assert repeated.should_log is False

    clock.advance(49.8)
    assert limiter.check([request_rule]).allowed


def test_expired_identity_cleanup_releases_bounded_capacity():
    clock = FakeClock()
    limiter = RollingWindowRateLimiter(max_identities=1, clock=clock)

    assert limiter.check([rule(identity="first", window=10)]).allowed
    with pytest.raises(RateLimiterUnavailable) as first_error:
        limiter.check([rule(identity="second", window=10)])
    assert first_error.value.should_log is True

    with pytest.raises(RateLimiterUnavailable) as repeated_error:
        limiter.check([rule(identity="second", window=10)])
    assert repeated_error.value.should_log is False

    clock.advance(10)
    assert limiter.check([rule(identity="second", window=10)]).allowed
    assert limiter.active_identity_count == 1


def test_policy_namespaces_are_independent_for_one_identity():
    limiter = RollingWindowRateLimiter(max_identities=1, clock=FakeClock())

    assert limiter.check([rule(policy="get", limit=1)]).allowed
    assert limiter.check([rule(policy="post", limit=1)]).allowed
    assert limiter.check([rule(policy="get", limit=1)]).allowed is False
    assert limiter.check([rule(policy="post", limit=1)]).allowed is False
    assert limiter.active_identity_count == 1


def test_thread_safety_never_allows_more_than_the_quota():
    limiter = RollingWindowRateLimiter(max_identities=10, clock=FakeClock())
    request_rule = rule(limit=5)

    with ThreadPoolExecutor(max_workers=20) as executor:
        decisions = list(
            executor.map(
                lambda _: limiter.check([request_rule]).allowed,
                range(40),
            )
        )

    assert sum(decisions) == 5


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("192.0.2.9", "192.0.2.9"),
        ("2001:db8:abcd:12::1", "2001:db8:abcd:12::/64"),
        ("2001:db8:abcd:12:ffff::9", "2001:db8:abcd:12::/64"),
    ],
)
def test_client_host_canonicalization(host: str, expected: str):
    assert canonicalize_client_host(host) == expected


def test_keyed_identity_is_deterministic_and_retains_no_raw_identifier(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "SECRET_KEY", "rate-limit-test-secret")
    raw_email = "buyer@example.com"

    first = keyed_identity("email", raw_email)
    second = keyed_identity("email", raw_email)

    assert first == second
    assert raw_email not in first
    assert keyed_identity("capability", raw_email) != first


def test_feedback_is_denied_before_service_execution(
    client,
    monkeypatch: pytest.MonkeyPatch,
    controlled_limiter,
):
    submit = Mock(return_value=SimpleNamespace(id=42))
    monkeypatch.setattr("app.api.v1.routes.submit_feedback", submit)
    payload = {
        "message_type": "general_question",
        "subject": "Rate limit test",
        "message": "A complete feedback message.",
    }

    for _ in range(5):
        assert client.post("/v1/feedback", data=payload).status_code == 200

    denied = client.post(
        "/v1/feedback",
        data=payload,
        files={"files": ("evidence.pdf", b"private attachment", "application/pdf")},
    )

    assert denied.status_code == 429
    assert denied.json() == {"detail": RATE_LIMIT_MESSAGE}
    assert denied.headers["retry-after"] == "900"
    assert submit.call_count == 5


def test_feedback_daily_quota_remains_after_short_windows_expire(
    client,
    monkeypatch: pytest.MonkeyPatch,
    controlled_limiter,
):
    submit = Mock(return_value=SimpleNamespace(id=42))
    monkeypatch.setattr("app.api.v1.routes.submit_feedback", submit)
    _, clock = controlled_limiter
    payload = {
        "message_type": "general_question",
        "subject": "Daily rate limit test",
        "message": "A complete daily rate-limit test message.",
    }

    for batch in range(4):
        for _ in range(5):
            assert client.post("/v1/feedback", data=payload).status_code == 200
        if batch < 3:
            clock.advance(15 * 60)

    denied = client.post("/v1/feedback", data=payload)
    assert denied.status_code == 429
    assert denied.headers["retry-after"] == str(24 * 60 * 60 - 45 * 60)
    assert submit.call_count == 20


def test_purchase_ip_and_normalized_email_quotas_are_independent(
    client,
    monkeypatch: pytest.MonkeyPatch,
    controlled_limiter,
):
    lookup = Mock(return_value=[])
    monkeypatch.setattr(
        "app.api.v1.routes.list_verified_product_purchases",
        lookup,
    )

    for index in range(10):
        email = "BUYER@example.com" if index % 2 else "buyer@example.com"
        assert (
            client.post("/v1/check-purchase", json={"email": email}).status_code == 200
        )

    email_denied = client.post(
        "/v1/check-purchase",
        json={"email": "buyer@example.com"},
    )
    assert email_denied.status_code == 429
    assert email_denied.headers["retry-after"] == "3600"

    assert (
        client.post(
            "/v1/check-purchase",
            json={"email": "other@example.com"},
        ).status_code
        == 200
    )
    ip_denied = client.post(
        "/v1/check-purchase",
        json={"email": "third@example.com"},
    )
    assert ip_denied.status_code == 429
    assert ip_denied.headers["retry-after"] == "600"
    assert lookup.call_count == 11


def test_spoofed_forwarded_headers_do_not_change_the_client_bucket(
    client,
    monkeypatch: pytest.MonkeyPatch,
    controlled_limiter,
):
    monkeypatch.setattr(
        "app.api.v1.routes.list_verified_product_purchases",
        lambda **kwargs: [],
    )

    for index in range(12):
        response = client.post(
            "/v1/check-purchase",
            json={"email": f"buyer-{index}@example.com"},
            headers={
                "Forwarded": f"for=192.0.2.{index + 1}",
                "X-Forwarded-For": f"192.0.2.{index + 1}",
            },
        )
        assert response.status_code == 200

    denied = client.post(
        "/v1/check-purchase",
        json={"email": "buyer-final@example.com"},
        headers={"X-Forwarded-For": "203.0.113.200"},
    )
    assert denied.status_code == 429


def test_download_post_limit_is_separate_and_denial_skips_service_and_signing(
    client,
    monkeypatch: pytest.MonkeyPatch,
    controlled_limiter,
):
    release = SimpleNamespace(
        storage_key="private/storage-key",
        original_filename="SmartBudget.zip",
    )
    entitlement = SimpleNamespace(
        release=release,
        support_reference="DL-ABCDEFGH",
    )
    record_attempt = Mock(return_value=entitlement)
    sign = Mock(return_value="https://r2.example/signed")

    class FakeStorage:
        generate_signed_get_url = sign

    monkeypatch.setattr(
        "app.web.routes.record_download_attempt",
        record_attempt,
    )
    monkeypatch.setattr("app.web.routes.R2StorageService", FakeStorage)

    for _ in range(5):
        response = client.post("/download/private-token", follow_redirects=False)
        assert response.status_code == 303

    denied = client.post("/download/private-token", follow_redirects=False)
    assert denied.status_code == 429
    assert denied.headers["retry-after"] == "900"
    assert_capability_headers(denied)
    assert "private-token" not in denied.text
    assert record_attempt.call_count == 5
    assert sign.call_count == 5

    get_response = client.get("/download/private-token")
    assert get_response.status_code == 404


@pytest.mark.parametrize(
    "path",
    (
        "/download/private-get-token",
        "/consultation/book/private-get-token",
    ),
)
def test_capability_get_limits_are_applied_per_capability(
    client,
    controlled_limiter,
    path,
):
    for _ in range(30):
        response = client.get(path)
        assert response.status_code == 404
        assert_capability_headers(response)

    denied = client.get(path)
    assert denied.status_code == 429
    assert denied.headers["retry-after"] == "900"
    assert_capability_headers(denied)
    assert "private-get-token" not in denied.text


def test_unsupported_consultation_method_keeps_405_then_returns_protected_429(
    client,
    controlled_limiter,
):
    for _ in range(5):
        response = client.post("/consultation/book/private-token?lang=ru")
        assert response.status_code == 405
        assert_capability_headers(response)

    denied = client.post("/consultation/book/private-token?lang=ru")
    assert denied.status_code == 429
    assert denied.headers["retry-after"] == "900"
    assert_capability_headers(denied)
    assert "Слишком много запросов" in denied.text
    assert "private-token" not in denied.text


def test_unsupported_download_method_keeps_405_then_returns_protected_429(
    client,
    controlled_limiter,
):
    for _ in range(5):
        assert client.put("/download/private-token").status_code == 405

    denied = client.put("/download/private-token")
    assert denied.status_code == 429
    assert denied.headers["retry-after"] == "900"
    assert_capability_headers(denied)


def test_admin_login_and_invalid_cookie_routes_share_one_failure_bucket(
    client,
    monkeypatch: pytest.MonkeyPatch,
    controlled_limiter,
):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "correct-admin-token")

    for _ in range(3):
        assert (
            client.post(
                "/admin/login",
                data={"token": "wrong"},
                follow_redirects=False,
            ).status_code
            == 403
        )
    for _ in range(2):
        client.cookies.set(ADMIN_COOKIE_NAME, "wrong")
        assert client.get("/admin").status_code == 403

    denied = client.get("/v1/feedback/recent")
    assert denied.status_code == 429
    assert denied.json() == {"detail": RATE_LIMIT_MESSAGE}
    assert denied.headers["retry-after"] == "900"


def test_admin_login_rate_limit_uses_english_html_without_echoing_credential(
    client,
    monkeypatch: pytest.MonkeyPatch,
    controlled_limiter,
):
    credential = "private-admin-credential"
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "correct-admin-token")

    for _ in range(5):
        assert (
            client.post(
                "/admin/login",
                data={"token": credential},
                follow_redirects=False,
            ).status_code
            == 403
        )

    denied = client.post(
        "/admin/login",
        data={"token": credential},
        follow_redirects=False,
    )
    assert denied.status_code == 429
    assert denied.headers["retry-after"] == "900"
    assert "Too many requests" in denied.text
    assert credential not in denied.text


def test_valid_admin_operations_do_not_consume_authentication_quota(
    client,
    monkeypatch: pytest.MonkeyPatch,
    controlled_limiter,
):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "correct-admin-token")
    client.cookies.set(ADMIN_COOKIE_NAME, "correct-admin-token")

    for _ in range(20):
        assert client.get("/admin").status_code == 200

    client.cookies.clear()
    for _ in range(5):
        assert (
            client.post(
                "/admin/login",
                data={"token": "wrong"},
                follow_redirects=False,
            ).status_code
            == 403
        )
    assert (
        client.post(
            "/admin/login",
            data={"token": "correct-admin-token"},
            follow_redirects=False,
        ).status_code
        == 429
    )


def test_webhook_preverification_limit_blocks_before_signature_work(
    client,
    monkeypatch: pytest.MonkeyPatch,
    controlled_limiter,
):
    verify = Mock(return_value=False)
    process = Mock()
    monkeypatch.setattr("app.api.v1.webhooks.verify_webhook_signature", verify)
    monkeypatch.setattr("app.api.v1.webhooks.process_calendly_webhook", process)

    for _ in range(120):
        assert client.post("/v1/webhooks/calendly", json={}).status_code == 401

    denied = client.post("/v1/webhooks/calendly", json={"private": "payload"})
    assert denied.status_code == 429
    assert denied.json() == {"detail": RATE_LIMIT_MESSAGE}
    assert denied.headers["retry-after"] == "60"
    assert verify.call_count == 120
    process.assert_not_called()


def test_verified_webhook_signature_limit_blocks_reconciliation_and_commit(
    client,
    monkeypatch: pytest.MonkeyPatch,
    controlled_limiter,
):
    process = Mock()
    monkeypatch.setattr(
        "app.api.v1.webhooks.verify_webhook_signature",
        lambda **kwargs: True,
    )
    monkeypatch.setattr("app.api.v1.webhooks.process_calendly_webhook", process)
    headers = {"Calendly-Webhook-Signature": "t=1,v1=private-signature"}

    for _ in range(10):
        response = client.post(
            "/v1/webhooks/calendly",
            json={"event": "ignored.test"},
            headers=headers,
        )
        assert response.status_code == 204

    denied = client.post(
        "/v1/webhooks/calendly",
        json={"event": "invitee.created"},
        headers=headers,
    )
    assert denied.status_code == 429
    assert denied.headers["retry-after"] == "180"
    assert process.call_count == 10


def test_verified_webhook_provider_namespace_has_approved_shared_limit(
    monkeypatch: pytest.MonkeyPatch,
):
    limiter = RollingWindowRateLimiter(max_identities=1000, clock=FakeClock())
    monkeypatch.setattr(app.state, "rate_limiter", limiter)
    request = Request(
        {
            "type": "http",
            "app": app,
            "method": "POST",
            "path": "/v1/webhooks/calendly",
            "headers": [],
            "client": ("192.0.2.10", 50000),
            "scheme": "https",
            "server": ("testserver", 443),
            "query_string": b"",
            "root_path": "",
            "http_version": "1.1",
        }
    )

    for index in range(300):
        enforce_calendly_verified_limits(request, f"signature-{index}")

    with pytest.raises(RateLimitExceeded) as exc_info:
        enforce_calendly_verified_limits(request, "signature-final")

    assert exc_info.value.policy_name == "calendly_provider_5m"
    assert exc_info.value.retry_after == 300


def test_capacity_exhaustion_fails_closed_and_keeps_capability_headers(
    client,
    monkeypatch: pytest.MonkeyPatch,
):
    limiter = RollingWindowRateLimiter(max_identities=1, clock=FakeClock())
    monkeypatch.setattr(app.state, "rate_limiter", limiter)
    monkeypatch.setattr(
        "app.api.v1.routes.submit_feedback",
        lambda **kwargs: SimpleNamespace(id=1),
    )

    assert (
        client.post(
            "/v1/feedback",
            data={
                "message_type": "general_question",
                "subject": "Capacity test",
                "message": "A complete capacity test message.",
            },
        ).status_code
        == 200
    )

    unavailable = client.get("/download/private-capability")
    assert unavailable.status_code == 503
    assert_capability_headers(unavailable)
    assert "private-capability" not in unavailable.text


def test_rate_limit_logging_is_coalesced_and_contains_no_sensitive_value(
    client,
    controlled_limiter,
    caplog: pytest.LogCaptureFixture,
):
    token = "private-capability-token"
    caplog.set_level(logging.WARNING, logger="app.core.rate_limiting")

    for _ in range(7):
        client.post(f"/consultation/book/{token}")

    records = [
        record
        for record in caplog.records
        if record.name == "app.core.rate_limiting"
        and record.getMessage() == "Request rate limited"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.route_template == "/consultation/book/{token}"
    assert record.identity_kind in {"capability", "client_ip"}
    assert token not in record.getMessage()
    assert token not in record.__dict__.values()


def test_ordinary_endpoints_and_admin_login_get_remain_unthrottled(
    client,
    controlled_limiter,
):
    paths = (
        "/",
        "/products",
        "/faq",
        "/feedback",
        "/admin/login",
        "/v1/health",
        "/v1/version",
        "/docs",
        "/static/css/style.css",
    )

    for _ in range(20):
        for path in paths:
            assert client.get(path).status_code == 200

    assert app.state.rate_limiter.active_identity_count == 0


def test_legacy_feedback_router_remains_unmounted():
    mounted_endpoint_names = {
        getattr(route.endpoint, "__name__", "")
        for route in app.routes
        if hasattr(route, "endpoint")
    }

    assert "create_feedback_endpoint" not in mounted_endpoint_names
