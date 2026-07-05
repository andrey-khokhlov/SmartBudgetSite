from datetime import datetime

from fastapi.testclient import TestClient

from app.models.feedback import FeedbackMessage
from app.models.product import Product


def test_reviews_page_returns_200(client: TestClient, db_session) -> None:
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

    response = client.get("/reviews")

    assert response.status_code == 200
    assert "Reviews" in response.text or "Отзывы" in response.text


def test_reviews_page_shows_only_published_product_feedback(client, db_session):
    product = Product(
        family_slug="smartbudget",
        slug="smartbudget",
        name="SmartBudget",
        edition="Standard",

        status="in_sale",
        archive_path="test/path.zip",
    )
    other_product = Product(
        family_slug="smartbudget",
        slug="other-product",
        name="Other Product",
        edition="Standard",

        status="in_sale",
        archive_path="test/path.zip",
    )
    db_session.add_all([product, other_product])
    db_session.commit()
    db_session.refresh(product)
    db_session.refresh(other_product)

    published_review = FeedbackMessage(
        type="product_feedback",
        name="User 1",
        email="u1@example.com",
        subject="Visible review",
        message="This should be visible",
        admin_reply="Reply",
        is_published=True,
        published_at=datetime(2026, 4, 1, 10, 0, 0),
        product_id=product.id,
    )

    hidden_review = FeedbackMessage(
        type="product_feedback",
        name="User 2",
        email="u2@example.com",
        subject="Hidden review",
        message="This should NOT be visible",
        admin_reply="Reply",
        is_published=False,
        product_id=product.id,
    )

    general_question = FeedbackMessage(
        type="general_question",
        name="User 3",
        email="u3@example.com",
        subject="Question",
        message="Also should NOT be visible",
        admin_reply="Reply",
        is_published=True,
        published_at=datetime(2026, 4, 2, 10, 0, 0),
        product_id=product.id,
    )

    other_product_review = FeedbackMessage(
        type="product_feedback",
        name="User 4",
        email="u4@example.com",
        subject="Other product review",
        message="Should NOT be visible",
        admin_reply="Reply",
        is_published=True,
        published_at=datetime(2026, 4, 3, 10, 0, 0),
        product_id=other_product.id,
    )

    db_session.add_all([
        published_review,
        hidden_review,
        general_question,
        other_product_review,
    ])
    db_session.commit()

    response = client.get("/reviews")

    assert response.status_code == 200
    assert "Visible review" in response.text
    assert "Hidden review" not in response.text
    assert "Question" not in response.text
    assert "Other product review" not in response.text
