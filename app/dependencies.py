"""
Application dependencies.

Important:
- Use get_db from this module everywhere in routes
- Do not duplicate get_db in other modules
"""

from collections.abc import Generator
from sqlalchemy.orm import Session
from fastapi import HTTPException, Request

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.rate_limiting import enforce_admin_auth_failure_limit

ADMIN_COOKIE_NAME = "admin_token"


def get_db() -> Generator[Session, None, None]:
    # Provide a database session per request
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_admin(request: Request) -> None:
    """
    Ensures that request is made by authenticated admin.

    Business rules:
    - Access allowed only if cookie matches admin_token

    Side effects:
    - None

    Invariants:
    - Raises 403 if not authenticated
    """

    if request.cookies.get(ADMIN_COOKIE_NAME) != settings.ADMIN_TOKEN:
        enforce_admin_auth_failure_limit(request)
        raise HTTPException(status_code=403, detail="Admin access denied")
