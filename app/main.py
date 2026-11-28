from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles

from .core.config import settings
from .core.capability_protection import CapabilityResponseProtectionMiddleware
from .core.logging import setup_logging
from .core.perimeter_rate_limiting import PerimeterRateLimiter
from .core.rate_limiting import (
    RateLimitExceeded,
    RateLimiterUnavailable,
    RateLimitMiddleware,
    RollingWindowRateLimiter,
)
from .core.trusted_proxy import TrustedProxyMiddleware
from .api.v1.routes import router as v1_router
from .api.v1.perimeter import router as perimeter_router
from app.web.routes import router as web_router
from app.web.rate_limit_responses import build_rate_limit_response


def create_app() -> FastAPI:
    setup_logging()

    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    application.state.rate_limiter = RollingWindowRateLimiter(
        max_identities=settings.RATE_LIMIT_MAX_IDENTITIES,
    )
    application.add_exception_handler(
        RateLimitExceeded,
        build_rate_limit_response,
    )
    application.add_exception_handler(
        RateLimiterUnavailable,
        build_rate_limit_response,
    )

    origins = [o.strip() for o in settings.BACKEND_CORS_ORIGINS.split(",") if o.strip()]
    if settings.APP_ENV == "dev" and not origins:
        origins = ["*"]

    application.add_middleware(
        RateLimitMiddleware,
        response_factory=build_rate_limit_response,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if settings.APP_ENV == "prod":
        application.state.perimeter_rate_limiter = PerimeterRateLimiter(
            max_buckets=settings.RATE_LIMIT_MAX_IDENTITIES,
        )
        application.state.perimeter_caddy_peer = settings.SMARTBUDGET_CADDY_PEER
        application.include_router(perimeter_router)
        application.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=[settings.SMARTBUDGET_HOST, "127.0.0.1"],
            www_redirect=False,
        )
        application.add_middleware(
            TrustedProxyMiddleware, peer=settings.SMARTBUDGET_CADDY_PEER
        )
    application.add_middleware(CapabilityResponseProtectionMiddleware)

    application.mount("/static", StaticFiles(directory="app/static"), name="static")

    application.include_router(v1_router)
    application.include_router(web_router)

    return application


app = create_app()
