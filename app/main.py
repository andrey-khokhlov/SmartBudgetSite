from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .core.config import settings
from .core.capability_protection import CapabilityResponseProtectionMiddleware
from .core.logging import setup_logging
from .core.rate_limiting import (
    RateLimitExceeded,
    RateLimiterUnavailable,
    RateLimitMiddleware,
    RollingWindowRateLimiter,
)
from .api.v1.routes import router as v1_router
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
    application.add_middleware(CapabilityResponseProtectionMiddleware)

    application.mount("/static", StaticFiles(directory="app/static"), name="static")

    application.include_router(v1_router)
    application.include_router(web_router)

    return application


app = create_app()
