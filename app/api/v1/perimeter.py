import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.core.capability_protection import CAPABILITY_RESPONSE_HEADERS
from app.core.perimeter_rate_limiting import (
    PERIMETER_POLICIES,
    perimeter_client_identity,
)
from app.core.rate_limiting import (
    RATE_LIMIT_MESSAGE,
    RATE_LIMIT_UNAVAILABLE_MESSAGE,
    RateLimiterUnavailable,
)

router = APIRouter(include_in_schema=False)
logger = logging.getLogger(__name__)

PERIMETER_AUTH_PATH = "/_internal/perimeter/check"


@router.get(PERIMETER_AUTH_PATH)
def check_perimeter(request: Request) -> Response:
    peer = request.app.state.perimeter_caddy_peer
    if (
        peer is None
        or request.client is None
        or getattr(request.state, "trusted_proxy_peer", None) != str(peer)
    ):
        return Response(status_code=404)

    policies = request.headers.getlist("x-forwarded-perimeter-policy")
    policy = PERIMETER_POLICIES.get(policies[0]) if len(policies) == 1 else None
    headers = {}
    if policy is not None and policy.capability:
        headers.update(
            (name.decode("ascii"), value.decode("ascii"))
            for name, value in CAPABILITY_RESPONSE_HEADERS
        )

    fields = {
        "method": "GET",
        "route_template": PERIMETER_AUTH_PATH,
    }
    try:
        if policy is None:
            raise ValueError("Invalid perimeter metadata")
        identity = perimeter_client_identity(request.client.host)
        decision = request.app.state.perimeter_rate_limiter.check(policies[0], identity)
    except Exception as exc:
        # Exception text can include client-provided data.
        if not isinstance(exc, RateLimiterUnavailable) or exc.should_log:
            logger.error(
                "Perimeter rate limiter unavailable",
                extra={
                    **fields,
                    "policy_name": "perimeter_unavailable",
                    "identity_kind": "none",
                    "status": "unavailable",
                },
            )
        return JSONResponse(
            status_code=503,
            content={"detail": RATE_LIMIT_UNAVAILABLE_MESSAGE},
            headers=headers,
        )

    if decision.allowed:
        return Response(status_code=204)

    if decision.should_log:
        logger.warning(
            "Perimeter rate limit exceeded",
            extra={
                **fields,
                "policy_name": decision.policy_name,
                "identity_kind": decision.identity_kind,
                "status": "rate_limited",
                "retry_after": decision.retry_after,
            },
        )
    headers["Retry-After"] = str(decision.retry_after)
    return JSONResponse(
        status_code=429, content={"detail": RATE_LIMIT_MESSAGE}, headers=headers
    )
