from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import math
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from fastapi import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings

RATE_LIMIT_MESSAGE = "Too many requests. Please try again later."
RATE_LIMIT_UNAVAILABLE_MESSAGE = "Request protection is temporarily unavailable."

FEEDBACK_PATH = "/v1/feedback"
PURCHASE_LOOKUP_PATH = "/v1/check-purchase"
ADMIN_LOGIN_PATH = "/admin/login"
CALENDLY_WEBHOOK_PATH = "/v1/webhooks/calendly"
LAVA_TOP_WEBHOOK_PATH = "/v1/webhooks/lava-top/payment-result"

DOWNLOAD_PATH_PATTERN = re.compile(r"^/download/([^/]+)(/.*)?$")
CONSULTATION_PATH_PATTERN = re.compile(r"^/consultation/book/([^/]+)(/.*)?$")
CHECKOUT_PATH_PATTERN = re.compile(r"^/checkout/[^/]+$")

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateLimitRule:
    policy_name: str
    limit: int
    window_seconds: int
    identity_kind: str
    identity_key: str


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int | None = None
    policy_name: str | None = None
    identity_kind: str | None = None
    should_log: bool = False


@dataclass
class _Bucket:
    timestamps: deque[float]
    window_seconds: int
    rejection_logged_until: float | None = None


class RateLimiterUnavailable(Exception):
    def __init__(
        self,
        *,
        route_template: str,
        method: str,
        response_kind: str,
        admin_document: bool = False,
        should_log: bool = True,
    ) -> None:
        super().__init__(RATE_LIMIT_UNAVAILABLE_MESSAGE)
        self.route_template = route_template
        self.method = method
        self.response_kind = response_kind
        self.admin_document = admin_document
        self.should_log = should_log


class RateLimitExceeded(Exception):
    def __init__(
        self,
        *,
        retry_after: int,
        policy_name: str,
        identity_kind: str,
        route_template: str,
        method: str,
        response_kind: str,
        admin_document: bool = False,
        provider: str | None = None,
    ) -> None:
        super().__init__(RATE_LIMIT_MESSAGE)
        self.retry_after = retry_after
        self.policy_name = policy_name
        self.identity_kind = identity_kind
        self.route_template = route_template
        self.method = method
        self.response_kind = response_kind
        self.admin_document = admin_document
        self.provider = provider


class RollingWindowRateLimiter:
    """Thread-safe, process-local rolling-window request limiter."""

    def __init__(
        self,
        *,
        max_identities: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_identities <= 0:
            raise ValueError("max_identities must be positive")

        self.max_identities = max_identities
        self._clock = clock
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._identity_refcounts: dict[str, int] = {}
        self._lock = threading.RLock()
        self._next_cleanup_at = 0.0
        self._capacity_log_emitted = False

    def check(self, rules: Iterable[RateLimitRule]) -> RateLimitDecision:
        checked_rules = tuple(rules)
        if not checked_rules:
            return RateLimitDecision(allowed=True)

        now = self._clock()
        with self._lock:
            if now >= self._next_cleanup_at:
                self._cleanup_expired(now)
                self._next_cleanup_at = now + 60.0

            for rule in checked_rules:
                self._validate_rule(rule)
                bucket = self._buckets.get((rule.policy_name, rule.identity_key))
                if bucket is not None:
                    self._expire_bucket_timestamps(bucket, now)

            new_identity_keys = {
                rule.identity_key
                for rule in checked_rules
                if rule.identity_key not in self._identity_refcounts
            }
            if len(self._identity_refcounts) + len(new_identity_keys) > (
                self.max_identities
            ):
                self._cleanup_expired(now)
                new_identity_keys = {
                    rule.identity_key
                    for rule in checked_rules
                    if rule.identity_key not in self._identity_refcounts
                }
                if len(self._identity_refcounts) + len(new_identity_keys) > (
                    self.max_identities
                ):
                    should_log = not self._capacity_log_emitted
                    self._capacity_log_emitted = True
                    raise RateLimiterUnavailable(
                        route_template="",
                        method="",
                        response_kind="api",
                        should_log=should_log,
                    )

            blocked: list[tuple[int, RateLimitRule, _Bucket, float]] = []
            for rule in checked_rules:
                bucket = self._buckets.get((rule.policy_name, rule.identity_key))
                if bucket is None or len(bucket.timestamps) < rule.limit:
                    continue

                release_at = bucket.timestamps[0] + rule.window_seconds
                retry_after = max(1, math.ceil(release_at - now))
                blocked.append((retry_after, rule, bucket, release_at))

            if blocked:
                retry_after, rule, bucket, release_at = max(
                    blocked,
                    key=lambda item: (item[0], item[1].policy_name),
                )
                should_log = (
                    bucket.rejection_logged_until is None
                    or now >= bucket.rejection_logged_until
                )
                if should_log:
                    bucket.rejection_logged_until = release_at
                return RateLimitDecision(
                    allowed=False,
                    retry_after=retry_after,
                    policy_name=rule.policy_name,
                    identity_kind=rule.identity_kind,
                    should_log=should_log,
                )

            for rule in checked_rules:
                bucket_key = (rule.policy_name, rule.identity_key)
                bucket = self._buckets.get(bucket_key)
                if bucket is None:
                    bucket = _Bucket(
                        timestamps=deque(),
                        window_seconds=rule.window_seconds,
                    )
                    self._buckets[bucket_key] = bucket
                    self._identity_refcounts[rule.identity_key] = (
                        self._identity_refcounts.get(rule.identity_key, 0) + 1
                    )
                bucket.timestamps.append(now)
                bucket.rejection_logged_until = None

            return RateLimitDecision(allowed=True)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()
            self._identity_refcounts.clear()
            self._next_cleanup_at = 0.0
            self._capacity_log_emitted = False

    @property
    def active_identity_count(self) -> int:
        with self._lock:
            return len(self._identity_refcounts)

    def _cleanup_expired(self, now: float) -> None:
        expired_bucket_keys: list[tuple[str, str]] = []
        for bucket_key, bucket in self._buckets.items():
            self._expire_bucket_timestamps(bucket, now)
            if not bucket.timestamps:
                expired_bucket_keys.append(bucket_key)

        for bucket_key in expired_bucket_keys:
            identity_key = bucket_key[1]
            del self._buckets[bucket_key]
            remaining = self._identity_refcounts[identity_key] - 1
            if remaining:
                self._identity_refcounts[identity_key] = remaining
            else:
                del self._identity_refcounts[identity_key]

        if len(self._identity_refcounts) < self.max_identities:
            self._capacity_log_emitted = False

    @staticmethod
    def _expire_bucket_timestamps(bucket: _Bucket, now: float) -> None:
        cutoff = now - bucket.window_seconds
        while bucket.timestamps and bucket.timestamps[0] <= cutoff:
            bucket.timestamps.popleft()
        if not bucket.timestamps:
            bucket.rejection_logged_until = None

    @staticmethod
    def _validate_rule(rule: RateLimitRule) -> None:
        if rule.limit <= 0 or rule.window_seconds <= 0:
            raise ValueError("Rate-limit rules require positive limits and windows")
        if not rule.policy_name or not rule.identity_key:
            raise ValueError("Rate-limit rules require policy and identity keys")


def canonicalize_client_host(host: str | None) -> str:
    candidate = (host or "").strip()
    if not candidate:
        return "unknown"

    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return f"peer:{candidate.lower()}"

    if isinstance(address, ipaddress.IPv6Address):
        network = ipaddress.ip_network(f"{address}/64", strict=False)
        return f"{network.network_address.compressed}/64"
    return address.compressed


def keyed_identity(identity_kind: str, value: str) -> str:
    message = f"rate-limit:v1:{identity_kind}:{value}".encode("utf-8")
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def client_ip_identity(request: Request) -> str:
    host = request.client.host if request.client is not None else None
    return keyed_identity("client_ip", canonicalize_client_host(host))


def _rule(
    *,
    policy_name: str,
    limit: int,
    window_seconds: int,
    identity_kind: str,
    identity_key: str,
) -> RateLimitRule:
    return RateLimitRule(
        policy_name=policy_name,
        limit=limit,
        window_seconds=window_seconds,
        identity_kind=identity_kind,
        identity_key=identity_key,
    )


def _enforce(
    request: Request,
    *,
    rules: Iterable[RateLimitRule],
    route_template: str,
    response_kind: str,
    admin_document: bool = False,
    provider: str | None = None,
) -> None:
    if not settings.RATE_LIMIT_ENABLED:
        return

    try:
        limiter: RollingWindowRateLimiter = request.app.state.rate_limiter
        decision = limiter.check(rules)
    except RateLimiterUnavailable as exc:
        exc.route_template = route_template
        exc.method = request.method
        exc.response_kind = response_kind
        exc.admin_document = admin_document
        if exc.should_log:
            logger.error(
                "Rate limiter unavailable",
                extra={
                    "policy_name": "rate_limit_capacity",
                    "method": request.method,
                    "route_template": route_template,
                    "identity_kind": "none",
                    "status": "unavailable",
                },
            )
        raise
    except Exception as exc:
        logger.exception(
            "Rate limiter failed",
            extra={
                "policy_name": "rate_limit_internal",
                "method": request.method,
                "route_template": route_template,
                "identity_kind": "none",
                "status": "unavailable",
            },
        )
        raise RateLimiterUnavailable(
            route_template=route_template,
            method=request.method,
            response_kind=response_kind,
            admin_document=admin_document,
        ) from exc

    if decision.allowed:
        return

    if decision.should_log:
        log_fields = {
            "policy_name": decision.policy_name,
            "method": request.method,
            "route_template": route_template,
            "identity_kind": decision.identity_kind,
            "retry_after": decision.retry_after,
            "status": "rate_limited",
        }
        if provider is not None:
            log_fields["provider"] = provider
        logger.warning("Request rate limited", extra=log_fields)

    raise RateLimitExceeded(
        retry_after=decision.retry_after or 1,
        policy_name=decision.policy_name or "unknown",
        identity_kind=decision.identity_kind or "unknown",
        route_template=route_template,
        method=request.method,
        response_kind=response_kind,
        admin_document=admin_document,
        provider=provider,
    )


def enforce_purchase_email_limit(request: Request, email: str) -> None:
    normalized_email = email.strip().lower()
    identity_key = keyed_identity("email", normalized_email)
    _enforce(
        request,
        rules=(
            _rule(
                policy_name="purchase_email_60m",
                limit=10,
                window_seconds=60 * 60,
                identity_kind="email",
                identity_key=identity_key,
            ),
        ),
        route_template=PURCHASE_LOOKUP_PATH,
        response_kind="api",
    )


def enforce_admin_auth_failure_limit(request: Request) -> None:
    identity_key = client_ip_identity(request)
    _enforce(
        request,
        rules=(
            _rule(
                policy_name="admin_auth_ip_15m",
                limit=5,
                window_seconds=15 * 60,
                identity_kind="client_ip",
                identity_key=identity_key,
            ),
        ),
        route_template="/admin/{protected}",
        response_kind="api" if request.url.path.startswith("/v1/") else "html",
        admin_document=not request.url.path.startswith("/v1/"),
    )


def enforce_calendly_verified_limits(
    request: Request,
    signature_header: str,
) -> None:
    provider_identity = keyed_identity("provider", "calendly")
    signature_identity = keyed_identity("webhook_signature", signature_header)
    _enforce(
        request,
        rules=(
            _rule(
                policy_name="calendly_provider_5m",
                limit=300,
                window_seconds=5 * 60,
                identity_kind="provider",
                identity_key=provider_identity,
            ),
            _rule(
                policy_name="calendly_signature_3m",
                limit=10,
                window_seconds=3 * 60,
                identity_kind="webhook_signature",
                identity_key=signature_identity,
            ),
        ),
        route_template=CALENDLY_WEBHOOK_PATH,
        response_kind="api",
        provider="calendly",
    )


def enforce_lava_top_verified_limit(request: Request) -> None:
    provider_identity = keyed_identity("provider", "lava_top")
    _enforce(
        request,
        rules=(
            _rule(
                policy_name="lava_top_provider_5m",
                limit=300,
                window_seconds=5 * 60,
                identity_kind="provider",
                identity_key=provider_identity,
            ),
        ),
        route_template=LAVA_TOP_WEBHOOK_PATH,
        response_kind="api",
        provider="lava_top",
    )


class RateLimitMiddleware:
    """Apply approved pre-body limits only to abuse-sensitive route families."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        response_factory: Callable[[Request, Exception], Response],
    ) -> None:
        self.app = app
        self.response_factory = response_factory

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http" or not settings.RATE_LIMIT_ENABLED:
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        try:
            self._enforce_request(request)
        except (RateLimitExceeded, RateLimiterUnavailable) as exc:
            response = self.response_factory(request, exc)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

    @staticmethod
    def _enforce_request(request: Request) -> None:
        path = request.url.path
        normalized_path = path.rstrip("/") or "/"
        method = request.method.upper()
        ip_identity = client_ip_identity(request)

        if normalized_path == FEEDBACK_PATH and method == "POST":
            _enforce(
                request,
                rules=(
                    _rule(
                        policy_name="feedback_ip_15m",
                        limit=5,
                        window_seconds=15 * 60,
                        identity_kind="client_ip",
                        identity_key=ip_identity,
                    ),
                    _rule(
                        policy_name="feedback_ip_24h",
                        limit=20,
                        window_seconds=24 * 60 * 60,
                        identity_kind="client_ip",
                        identity_key=ip_identity,
                    ),
                ),
                route_template=FEEDBACK_PATH,
                response_kind="api",
            )
            return

        if normalized_path == PURCHASE_LOOKUP_PATH and method == "POST":
            _enforce(
                request,
                rules=(
                    _rule(
                        policy_name="purchase_ip_10m",
                        limit=12,
                        window_seconds=10 * 60,
                        identity_kind="client_ip",
                        identity_key=ip_identity,
                    ),
                ),
                route_template=PURCHASE_LOOKUP_PATH,
                response_kind="api",
            )
            return

        if CHECKOUT_PATH_PATTERN.match(normalized_path) and method == "POST":
            _enforce(
                request,
                rules=(
                    _rule(
                        policy_name="checkout_ip_10m",
                        limit=8,
                        window_seconds=10 * 60,
                        identity_kind="client_ip",
                        identity_key=ip_identity,
                    ),
                ),
                route_template="/checkout/{slug}",
                response_kind="html",
            )
            return

        if normalized_path == ADMIN_LOGIN_PATH and method == "POST":
            _enforce(
                request,
                rules=(
                    _rule(
                        policy_name="admin_auth_ip_15m",
                        limit=5,
                        window_seconds=15 * 60,
                        identity_kind="client_ip",
                        identity_key=ip_identity,
                    ),
                ),
                route_template=ADMIN_LOGIN_PATH,
                response_kind="html",
                admin_document=True,
            )
            return

        if normalized_path == CALENDLY_WEBHOOK_PATH and method == "POST":
            _enforce(
                request,
                rules=(
                    _rule(
                        policy_name="calendly_ip_1m",
                        limit=120,
                        window_seconds=60,
                        identity_kind="client_ip",
                        identity_key=ip_identity,
                    ),
                ),
                route_template=CALENDLY_WEBHOOK_PATH,
                response_kind="api",
                provider="calendly",
            )
            return

        if normalized_path == LAVA_TOP_WEBHOOK_PATH and method == "POST":
            _enforce(
                request,
                rules=(
                    _rule(
                        policy_name="lava_top_ip_1m",
                        limit=120,
                        window_seconds=60,
                        identity_kind="client_ip",
                        identity_key=ip_identity,
                    ),
                ),
                route_template=LAVA_TOP_WEBHOOK_PATH,
                response_kind="api",
                provider="lava_top",
            )
            return

        download_match = DOWNLOAD_PATH_PATTERN.match(path)
        if download_match is not None:
            capability_identity = keyed_identity(
                "download_capability",
                download_match.group(1),
            )
            if method == "GET" and download_match.group(2) is None:
                rules = (
                    _rule(
                        policy_name="download_get_ip_15m",
                        limit=60,
                        window_seconds=15 * 60,
                        identity_kind="client_ip",
                        identity_key=ip_identity,
                    ),
                    _rule(
                        policy_name="download_get_capability_15m",
                        limit=30,
                        window_seconds=15 * 60,
                        identity_kind="capability",
                        identity_key=capability_identity,
                    ),
                )
            elif method == "POST" and download_match.group(2) is None:
                rules = (
                    _rule(
                        policy_name="download_post_ip_15m",
                        limit=10,
                        window_seconds=15 * 60,
                        identity_kind="client_ip",
                        identity_key=ip_identity,
                    ),
                    _rule(
                        policy_name="download_post_capability_15m",
                        limit=5,
                        window_seconds=15 * 60,
                        identity_kind="capability",
                        identity_key=capability_identity,
                    ),
                )
            else:
                rules = (
                    _rule(
                        policy_name="download_unsupported_ip_15m",
                        limit=10,
                        window_seconds=15 * 60,
                        identity_kind="client_ip",
                        identity_key=ip_identity,
                    ),
                    _rule(
                        policy_name="download_unsupported_capability_15m",
                        limit=5,
                        window_seconds=15 * 60,
                        identity_kind="capability",
                        identity_key=capability_identity,
                    ),
                )
            _enforce(
                request,
                rules=rules,
                route_template="/download/{token}",
                response_kind="html",
            )
            return

        consultation_match = CONSULTATION_PATH_PATTERN.match(path)
        if consultation_match is not None:
            capability_identity = keyed_identity(
                "consultation_capability",
                consultation_match.group(1),
            )
            if method == "GET" and consultation_match.group(2) is None:
                rules = (
                    _rule(
                        policy_name="consultation_get_ip_15m",
                        limit=60,
                        window_seconds=15 * 60,
                        identity_kind="client_ip",
                        identity_key=ip_identity,
                    ),
                    _rule(
                        policy_name="consultation_get_capability_15m",
                        limit=30,
                        window_seconds=15 * 60,
                        identity_kind="capability",
                        identity_key=capability_identity,
                    ),
                )
            else:
                rules = (
                    _rule(
                        policy_name="consultation_unsupported_ip_15m",
                        limit=10,
                        window_seconds=15 * 60,
                        identity_kind="client_ip",
                        identity_key=ip_identity,
                    ),
                    _rule(
                        policy_name="consultation_unsupported_capability_15m",
                        limit=5,
                        window_seconds=15 * 60,
                        identity_kind="capability",
                        identity_key=capability_identity,
                    ),
                )
            _enforce(
                request,
                rules=rules,
                route_template="/consultation/book/{token}",
                response_kind="html",
            )
