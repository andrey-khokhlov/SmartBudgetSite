from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.db import Base
from app.dependencies import get_db
from app.main import app
from app.models.consultation_capacity import ConsultationCapacityState
from app.models.feedback import FeedbackMessage
from app.models.product import Product
from app.models.product_price import ProductPrice


@pytest.fixture
def checkout_legal_pages(monkeypatch):
    monkeypatch.setattr(settings, "REFUND_POLICY_PUBLICATION_DATE", date(2000, 1, 2))
    monkeypatch.setattr(settings, "SELLER_ADDRESS_RU", "Учебный адрес")
    monkeypatch.setattr(settings, "SELLER_ADDRESS_EN", "Fictional Seller Address")
    monkeypatch.setattr(settings, "SELLER_CONTACT_PHONE", "+1 202-555-0147")


@pytest.fixture
def review_sessions(monkeypatch):
    """Keep browser review reads and fixtures isolated from the local database."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Product.__table__,
            ProductPrice.__table__,
            FeedbackMessage.__table__,
            ConsultationCapacityState.__table__,
        ],
    )
    sessions = sessionmaker(bind=engine)
    with sessions.begin() as db:
        db.add(
            ConsultationCapacityState(
                id=1, manually_suspended=False, observed_level="normal"
            )
        )

    def test_db():
        with sessions() as db:
            yield db

    monkeypatch.setitem(app.dependency_overrides, get_db, test_db)
    try:
        yield sessions
    finally:
        engine.dispose()
