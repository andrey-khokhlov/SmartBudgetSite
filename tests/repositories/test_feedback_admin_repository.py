from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.models.feedback import FeedbackMessage
from app.models.product import Product
from app.services.product_service import set_product_price
from app.repositories.feedback_admin_repository import FeedbackAdminRepository


def test_list_published_product_feedback_returns_only_published_product_feedback(db_session):
    repo = FeedbackAdminRepository(db_session)

    product = Product(
        family_slug="smartbudget",
        slug="smartbudget",
        name="SmartBudget",
        edition="Standard",

        status="in_sale",
        archive_path="test/path.zip",
    )

    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)

    set_product_price(
        db=db_session,
        product_id=product.id,
        currency_code="RUB",
        amount=Decimal("49.00"),
    )

    other_product = Product(
        family_slug="smartbudget",
        slug="other-product",
        name="Other Product",
        edition="Standard",

        status="in_sale",
        archive_path="test/path.zip",
    )

    db_session.add(other_product)
    db_session.commit()
    db_session.refresh(other_product)

    old_review = FeedbackMessage(
        type="product_feedback",
        name="User 1",
        email="u1@example.com",
        subject="Old review",
        message="Old message",
        admin_reply="Reply 1",
        is_published=True,
        published_at=datetime(2026, 4, 1, 10, 0, 0),
        product_id=product.id,
    )

    new_review = FeedbackMessage(
        type="product_feedback",
        name="User 2",
        email="u2@example.com",
        subject="New review",
        message="New message",
        admin_reply="Reply 2",
        is_published=True,
        published_at=datetime(2026, 4, 2, 10, 0, 0),
        product_id=product.id,
    )

    hidden_product_feedback = FeedbackMessage(
        type="product_feedback",
        name="User 3",
        email="u3@example.com",
        subject="Draft review",
        message="Draft message",
        admin_reply="Reply 3",
        is_published=False,
        product_id=product.id,
    )

    general_question = FeedbackMessage(
        type="general_question",
        name="User 4",
        email="u4@example.com",
        subject="Question",
        message="Question message",
        admin_reply="Reply 4",
        is_published=True,
        published_at=datetime(2026, 4, 3, 10, 0, 0),
        product_id=product.id,
    )

    other_product_review = FeedbackMessage(
        type="product_feedback",
        name="User 5",
        email="u5@example.com",
        subject="Other product review",
        message="Other product message",
        admin_reply="Reply 5",
        is_published=True,
        published_at=datetime(2026, 4, 4, 10, 0, 0),
        product_id=other_product.id,
    )

    db_session.add_all([
        old_review,
        new_review,
        hidden_product_feedback,
        general_question,
        other_product_review,
    ])
    db_session.commit()

    result = repo.list_published_product_feedback(product_id=product.id)

    assert len(result) == 2
    assert result[0].subject == "New review"
    assert result[1].subject == "Old review"


