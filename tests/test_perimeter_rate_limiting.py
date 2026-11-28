import logging
import math
from concurrent.futures import ThreadPoolExecutor
from ipaddress import IPv4Address
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app import main
from app.api.v1.perimeter import PERIMETER_AUTH_PATH
from app.core.perimeter_rate_limiting import (
    PerimeterRateLimiter,
    perimeter_client_identity,
)
from app.core.rate_limiting import RateLimiterUnavailable
from tests.test_rate_limiting import FakeClock, assert_capability_headers


@pytest.mark.parametrize(
    ("policy", "rate", "burst"),
    [
        ("feedback", 10, 5),
        ("purchase_lookup", 30, 10),
        ("download_get", 120, 20),
        ("download_post", 30, 10),
        ("consultation_booking", 120, 20),
        ("admin_login", 20, 5),
        ("admin", 120, 20),
        ("calendly", 300, 100),
        ("lava_top", 300, 100),
    ],
)
def test_ip_token_bucket(policy: str, rate: int, burst: int) -> None:
    clock = FakeClock(initial=0)
    limiter = PerimeterRateLimiter(max_buckets=10, clock=clock)
    for _ in range(burst):
        assert limiter.check(policy, "one").allowed

    denied = limiter.check(policy, "one")
    assert not denied.allowed
    assert denied.retry_after == math.ceil(60 / rate)
    assert denied.policy_name == f"perimeter_{policy}"
    assert denied.should_log
    assert not limiter.check(policy, "one").should_log
    assert limiter.check(policy, "two").allowed

    clock.advance(60 / rate)
    assert limiter.check(policy, "one").allowed
    assert not limiter.check(policy, "one").allowed


def test_global_limit_is_shared_and_does_not_charge_denials() -> None:
    clock = FakeClock()
    limiter = PerimeterRateLimiter(max_buckets=3001, clock=clock)
    for _ in range(5):
        assert limiter.check("feedback", "first").allowed
    for _ in range(20):
        assert not limiter.check("feedback", "first").allowed

    clock.advance(1)
    for i in range(2995):
        assert limiter.check("admin", f"identity-{i}").allowed

    blocked = limiter.check("download_get", "first")
    assert not blocked.allowed
    assert blocked.policy_name == "perimeter_global_60s"
    assert blocked.retry_after == 59
    clock.advance(58.5)
    assert limiter.check("feedback", "recovery").retry_after == 1
    clock.advance(0.5)
    for _ in range(5):
        assert limiter.check("feedback", "recovery").allowed
    assert limiter.check("download_get", "first").retry_after == 1
    clock.advance(1)
    assert limiter.check("download_get", "first").allowed


def test_shared_ip_uses_independent_policy_buckets_under_concurrency() -> None:
    limiter = PerimeterRateLimiter(max_buckets=10, clock=FakeClock())
    with ThreadPoolExecutor(max_workers=12) as pool:
        decisions = list(pool.map(lambda _: limiter.check("admin", "one"), range(40)))

    assert sum(decision.allowed for decision in decisions) == 20
    assert sum(decision.should_log for decision in decisions) == 1
    assert limiter.check("admin_login", "one").allowed


def test_capacity_fails_closed_and_recovers_after_idle_buckets_expire() -> None:
    clock = FakeClock()
    limiter = PerimeterRateLimiter(max_buckets=1, clock=clock)
    assert limiter.check("feedback", "first").allowed
    with pytest.raises(RateLimiterUnavailable) as first:
        limiter.check("feedback", "second")
    with pytest.raises(RateLimiterUnavailable) as repeated:
        limiter.check("feedback", "third")
    assert first.value.should_log
    assert not repeated.value.should_log

    clock.advance(30)
    assert limiter.check("feedback", "second").allowed


def test_perimeter_identity_uses_ipv4_host_and_ipv6_prefix() -> None:
    v4 = perimeter_client_identity("192.0.2.1")
    assert v4 == perimeter_client_identity("::ffff:192.0.2.1")
    assert v4 != perimeter_client_identity("192.0.2.2")
    v6 = perimeter_client_identity("2001:db8::1")
    assert v6 == perimeter_client_identity("2001:db8::2")
    assert v6 != perimeter_client_identity("2001:db8:0:1::1")
    assert len(v6) == len(v4) == 64


@pytest.fixture
def production_app(monkeypatch):
    monkeypatch.setattr(main.settings, "APP_ENV", "prod")
    monkeypatch.setattr(main.settings, "SMARTBUDGET_HOST", "testserver")
    monkeypatch.setattr(
        main.settings, "SMARTBUDGET_CADDY_PEER", IPv4Address("192.0.2.2")
    )
    app = main.create_app()
    app.state.perimeter_rate_limiter = PerimeterRateLimiter(
        max_buckets=10, clock=FakeClock()
    )
    return app


def client_from(app, host: str) -> TestClient:
    return TestClient(app, client=(host, 50000), follow_redirects=False)


def auth_headers(policy: str, host: str = "198.51.100.1") -> dict[str, str]:
    return {
        "X-Forwarded-Perimeter-Policy": policy,
        "X-Forwarded-For": host,
        "X-Forwarded-Proto": "https",
    }


def test_only_exact_caddy_peer_can_authorize(production_app) -> None:
    headers = auth_headers("feedback")
    with client_from(production_app, "192.0.2.3") as direct:
        response = direct.get(
            PERIMETER_AUTH_PATH, headers={**headers, "X-Forwarded-For": "192.0.2.2"}
        )
        assert response.status_code == 404
    with client_from(production_app, "192.0.2.2") as caddy:
        assert caddy.get(PERIMETER_AUTH_PATH, headers=headers).status_code == 204


@pytest.mark.parametrize(
    "forwarded_headers",
    [
        [("X-Forwarded-For", "198.51.100.1, 198.51.100.2")],
        [("X-Forwarded-For", "198.51.100.1"), ("X-Forwarded-For", "198.51.100.2")],
        [("X-Forwarded-For", "fe80::1%eth0")],
        [("X-Forwarded-For", "198.51.100.1"), ("X-Forwarded-Proto", "https")],
    ],
)
def test_trusted_peer_rejects_ambiguous_forwarding(production_app, forwarded_headers):
    with client_from(production_app, "192.0.2.2") as caddy:
        response = caddy.get(
            PERIMETER_AUTH_PATH,
            headers=[
                ("X-Forwarded-Perimeter-Policy", "feedback"),
                ("X-Forwarded-Proto", "https"),
                *forwarded_headers,
            ],
        )
        assert response.status_code == 400


def test_forward_auth_and_original_request_use_separate_quotas(production_app) -> None:
    with client_from(production_app, "192.0.2.2") as caddy:
        for _ in range(5):
            assert (
                caddy.get(
                    PERIMETER_AUTH_PATH, headers=auth_headers("admin_login")
                ).status_code
                == 204
            )
            assert (
                caddy.post(
                    "/admin/login",
                    data={"token": "wrong"},
                    headers={
                        "X-Forwarded-For": "198.51.100.1",
                        "X-Forwarded-Proto": "https",
                    },
                ).status_code
                == 403
            )
        response = caddy.get(PERIMETER_AUTH_PATH, headers=auth_headers("admin_login"))
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "3"


def test_capability_denials_and_internal_errors_stay_private(
    production_app, caplog, monkeypatch
) -> None:
    headers = auth_headers("download_post", "2001:db8::1")
    same_prefix = auth_headers("download_post", "2001:db8::9")
    with client_from(production_app, "192.0.2.2") as caddy:
        for _ in range(10):
            assert caddy.get(PERIMETER_AUTH_PATH, headers=headers).status_code == 204

        with caplog.at_level(logging.WARNING, logger="app.api.v1.perimeter"):
            for _ in range(2):
                denied = caddy.get(PERIMETER_AUTH_PATH, headers=same_prefix)
                assert denied.status_code == 429
                assert denied.headers["Retry-After"] == "2"
                assert_capability_headers(denied)
            invalid = caddy.get(
                PERIMETER_AUTH_PATH, headers=auth_headers("download_post", "bogus-ip")
            )
            assert invalid.status_code == 400

            broken = Mock(side_effect=RuntimeError("internal secret"))
            monkeypatch.setattr(
                production_app.state.perimeter_rate_limiter, "check", broken
            )
            failed = caddy.get(PERIMETER_AUTH_PATH, headers=headers)
            assert failed.status_code == 503
            assert_capability_headers(failed)

    rejections = [
        record
        for record in caplog.records
        if getattr(record, "status", None) == "rate_limited"
    ]
    assert len(rejections) == 1
    assert "2001:db8::" not in caplog.text
    assert "bogus-ip" not in caplog.text
    assert "internal secret" not in caplog.text
