from __future__ import annotations

from collections.abc import MutableSequence

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import PAYMENT_RESULT_PATH

CAPABILITY_RESPONSE_HEADERS = (
    (b"cache-control", b"private, no-store, max-age=0"),
    (b"pragma", b"no-cache"),
    (b"expires", b"0"),
    (b"referrer-policy", b"no-referrer"),
)

PAYMENT_RESULT_RESPONSE_HEADERS = (
    (b"cache-control", b"no-store"),
    (b"referrer-policy", b"no-referrer"),
)

CAPABILITY_PATH_PREFIXES = (
    "/download/",
    "/consultation/book/",
)


def is_capability_path(path: str) -> bool:
    """Return whether a request path may contain a customer capability token."""
    return any(path.startswith(prefix) for prefix in CAPABILITY_PATH_PREFIXES)


def _replace_header(
    headers: MutableSequence[tuple[bytes, bytes]],
    name: bytes,
    value: bytes,
) -> None:
    headers[:] = [
        (header_name, header_value)
        for header_name, header_value in headers
        if header_name.lower() != name
    ]
    headers.append((name, value))


class CapabilityResponseProtectionMiddleware:
    """Apply cache and referrer protection to customer capability and result routes."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        if is_capability_path(path):
            response_headers = CAPABILITY_RESPONSE_HEADERS
        elif path in (PAYMENT_RESULT_PATH, f"{PAYMENT_RESULT_PATH}/"):
            response_headers = PAYMENT_RESULT_RESPONSE_HEADERS
        else:
            await self.app(scope, receive, send)
            return

        async def send_protected(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                for name, value in response_headers:
                    _replace_header(headers, name, value)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_protected)
