from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from app.core.i18n import get_lang, t
from app.core.rate_limiting import (
    RATE_LIMIT_MESSAGE,
    RATE_LIMIT_UNAVAILABLE_MESSAGE,
    RateLimitExceeded,
)

templates = Jinja2Templates(directory="app/templates")


def build_rate_limit_response(request: Request, exc: Exception):
    is_rate_limit = isinstance(exc, RateLimitExceeded)
    status_code = 429 if is_rate_limit else 503
    detail = RATE_LIMIT_MESSAGE if is_rate_limit else RATE_LIMIT_UNAVAILABLE_MESSAGE
    headers = {}
    if is_rate_limit:
        headers["Retry-After"] = str(exc.retry_after)

    if getattr(exc, "response_kind", "api") == "api":
        return JSONResponse(
            status_code=status_code,
            content={"detail": detail},
            headers=headers,
        )

    lang = "en" if getattr(exc, "admin_document", False) else get_lang(request)
    retry_after = getattr(exc, "retry_after", None)
    message_key = (
        "rate_limit_message" if is_rate_limit else "rate_limit_unavailable_message"
    )
    return templates.TemplateResponse(
        request=request,
        name="rate_limited.html",
        context={
            "lang": lang,
            "document_lang": lang,
            "t": lambda key: t(lang, key),
            "rate_limit_message": t(lang, message_key),
            "retry_message": (
                t(lang, "rate_limit_retry_after").format(seconds=retry_after)
                if retry_after is not None
                else None
            ),
        },
        status_code=status_code,
        headers=headers,
    )
