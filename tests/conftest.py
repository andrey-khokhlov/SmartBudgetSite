"""
conftest.py

This file contains shared pytest fixtures and test environment configuration.

Purpose:
- Provide an isolated test database (SQLite instead of PostgreSQL)
- Override FastAPI dependencies (get_db) to use the test database
- Create a clean database schema before tests and remove it after
- Provide a TestClient instance for API testing
- Redirect file uploads to a temporary directory during tests

Why this is important:
- Tests do not affect the real database or filesystem
- Each test runs in a controlled and predictable environment
- Makes tests reproducible and safe to run anytime

Key fixtures:
- client: FastAPI TestClient for sending HTTP requests
- db_session: direct access to test database session
- override_dependencies: injects test DB and temp upload folder
- setup_test_database: creates and drops tables for test session
"""

from __future__ import annotations

from pathlib import Path
from typing import Generator
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.core.db import Base

from app.dependencies import get_db, ADMIN_COOKIE_NAME
from app.core.config import settings

from app.services import mail_service

TEST_DB_FILE = Path(tempfile.gettempdir()) / "smartbudget_test_feedback.db"
TEST_DATABASE_URL = f"sqlite:///{TEST_DB_FILE}"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def override_get_db() -> Generator:
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def auth_client(client: TestClient) -> TestClient:
    """
    Return TestClient with valid admin auth cookie set.
    """
    client.cookies.set(ADMIN_COOKIE_NAME, settings.ADMIN_TOKEN)
    return client


@pytest.fixture(scope="session", autouse=True)
def setup_test_database() -> Generator[None, None, None]:
    # Clean old test DB file if it exists
    if TEST_DB_FILE.exists():
        TEST_DB_FILE.unlink()

    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    # Dispose SQLAlchemy engine to release SQLite file locks on Windows
    engine.dispose()

    if TEST_DB_FILE.exists():
        TEST_DB_FILE.unlink()


@pytest.fixture(autouse=True)
def clean_database() -> Generator[None, None, None]:
    """
    Ensure each test starts with a clean database state.

    Why this is important:
    - Prevents data leakage between tests
    - Avoids UNIQUE constraint conflicts
    - Makes tests independent and reproducible
    """
    db = TestingSessionLocal()
    try:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()
        yield
    finally:
        db.close()


@pytest.fixture(autouse=True)
def override_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None, None, None]:
    # Use a temporary uploads folder for each test
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(upload_dir), raising=False)

    app.state.rate_limiter.reset()
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
    app.state.rate_limiter.reset()


@pytest.fixture()
def db_session() -> Generator:
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def disable_real_email_sending(monkeypatch):
    """
    Block real SMTP sending in all tests.

    Replaces mail_service.send_email with a harmless stub.
    """
    sent_emails = []

    def fake_send_email(*, to_email: str, subject: str, body: str) -> None:
        sent_emails.append(
            {
                "to_email": to_email,
                "subject": subject,
                "body": body,
            }
        )

    monkeypatch.setattr(mail_service, "send_email", fake_send_email)

    return sent_emails
