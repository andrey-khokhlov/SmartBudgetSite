from ipaddress import IPv4Address, ip_address

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class TrustedProxyMiddleware:
    """Read single-hop forwarding headers after authenticating the TCP peer."""

    def __init__(self, app: ASGIApp, *, peer: IPv4Address | None) -> None:
        self.app = app
        self.peer = str(peer) if peer is not None else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        client = scope.get("client")
        if scope["type"] != "http" or not client or client[0] != self.peer:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        forwarded_ips = headers.getlist("x-forwarded-for")
        schemes = headers.getlist("x-forwarded-proto")
        try:
            if (
                len(forwarded_ips) != 1
                or "%" in forwarded_ips[0]
                or len(schemes) != 1
                or schemes[0] not in {"http", "https"}
            ):
                raise ValueError("Invalid single-hop forwarding headers")
            address = ip_address(forwarded_ips[0])
        except ValueError:
            response = PlainTextResponse("Invalid proxy headers", status_code=400)
            await response(scope, receive, send)
            return

        scope.setdefault("state", {})["trusted_proxy_peer"] = client[0]
        scope["client"] = (str(address), 0)
        scope["scheme"] = schemes[0]
        await self.app(scope, receive, send)
