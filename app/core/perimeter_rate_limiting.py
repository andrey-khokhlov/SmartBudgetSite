from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from ipaddress import IPv6Address, ip_address

from app.core.rate_limiting import (
    RateLimitDecision,
    RateLimiterUnavailable,
    RateLimitRule,
    RollingWindowRateLimiter,
    canonicalize_client_host,
    keyed_identity,
)


@dataclass(frozen=True)
class PerimeterPolicy:
    requests_per_minute: int
    burst: int
    capability: bool = False


PERIMETER_POLICIES = {
    "feedback": PerimeterPolicy(10, 5),
    "purchase_lookup": PerimeterPolicy(30, 10),
    "download_get": PerimeterPolicy(120, 20, capability=True),
    "download_post": PerimeterPolicy(30, 10, capability=True),
    "consultation_booking": PerimeterPolicy(120, 20, capability=True),
    "admin_login": PerimeterPolicy(20, 5),
    "admin": PerimeterPolicy(120, 20),
    "calendly": PerimeterPolicy(300, 100),
    "lava_top": PerimeterPolicy(300, 100),
}

_GLOBAL_RULE = RateLimitRule("perimeter_global_60s", 3000, 60, "global", "global")
_BUCKET_RETENTION_SECONDS = max(
    policy.burst * 60 / policy.requests_per_minute
    for policy in PERIMETER_POLICIES.values()
)


def perimeter_client_identity(host: str) -> str:
    if "%" in host:
        raise ValueError("A client IP must not have an interface scope")
    address = ip_address(host)
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return keyed_identity(
        "perimeter_client_ip", canonicalize_client_host(address.compressed)
    )


@dataclass
class _TokenBucket:
    tokens: float
    updated_at: float
    rejection_logged: bool = False


class PerimeterRateLimiter:
    """Bounded token buckets and a rolling global cap for approved edge requests."""

    def __init__(
        self,
        *,
        max_buckets: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_buckets <= 0:
            raise ValueError("max_buckets must be positive")
        self._max_buckets = max_buckets
        self._clock = clock
        self._global = RollingWindowRateLimiter(max_identities=1, clock=clock)
        self._buckets: OrderedDict[tuple[str, str], _TokenBucket] = OrderedDict()
        self._lock = threading.Lock()
        self._capacity_log_emitted = False

    def check(self, policy_name: str, identity_key: str) -> RateLimitDecision:
        policy = PERIMETER_POLICIES[policy_name]
        key = (policy_name, identity_key)
        with self._lock:
            now = self._clock()
            self._expire_buckets(now)
            bucket = self._buckets.get(key)
            tokens = float(policy.burst)
            if bucket is not None:
                tokens = min(
                    tokens,
                    bucket.tokens
                    + (now - bucket.updated_at) * policy.requests_per_minute / 60,
                )
                if tokens < 1:
                    should_log = not bucket.rejection_logged
                    bucket.rejection_logged = True
                    return RateLimitDecision(
                        allowed=False,
                        retry_after=max(
                            1, math.ceil((1 - tokens) * 60 / policy.requests_per_minute)
                        ),
                        policy_name=f"perimeter_{policy_name}",
                        identity_kind="client_ip",
                        should_log=should_log,
                    )
            elif len(self._buckets) >= self._max_buckets:
                should_log = not self._capacity_log_emitted
                self._capacity_log_emitted = True
                raise RateLimiterUnavailable(
                    route_template="",
                    method="GET",
                    response_kind="api",
                    should_log=should_log,
                )

            # Only debit the global quota if the IP bucket can also be charged.
            decision = self._global.check((_GLOBAL_RULE,))
            if decision.allowed:
                self._buckets[key] = _TokenBucket(tokens - 1, now)
                self._buckets.move_to_end(key)
            return decision

    def _expire_buckets(self, now: float) -> None:
        # Admission order bounds cleanup. Old buckets are guaranteed to be full.
        cutoff = now - _BUCKET_RETENTION_SECONDS
        while self._buckets and next(iter(self._buckets.values())).updated_at <= cutoff:
            self._buckets.popitem(last=False)
        if len(self._buckets) < self._max_buckets:
            self._capacity_log_emitted = False
