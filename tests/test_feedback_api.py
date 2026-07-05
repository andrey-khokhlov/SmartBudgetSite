# tests/test_feedback_api.py
from decimal import Decimal
from app.services.product_service import set_product_price

def test_create_general_feedback_success(client, db_session):
    """
    Test case: create general feedback message

    What we verify:
    - Endpoint /v1/feedback accepts a valid general_question payload
    - Response status is successful
    - Feedback record is stored in the database
    """

    from app.models.feedback import FeedbackMessage

    response = client.post(
        "/v1/feedback",
        data={
            "message_type": "general_question",
            "name": "Andrey",
            "email": "andrey@example.com",
            "subject": "Test subject",
            "message": "This is a valid test message with enough length.",
            "page_url": "http://localhost/test-page",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "ok"
    assert "id" in data

    saved_feedback = db_session.query(FeedbackMessage).filter_by(id=data["id"]).first()

    assert saved_feedback is not None
    assert saved_feedback.type == "general_question"
    assert saved_feedback.email == "andrey@example.com"
    assert saved_feedback.subject == "Test subject"

def test_create_product_feedback_without_verified_purchase(client):
    """
    Test case: create product feedback without verified purchase

    What we verify:
    - Endpoint /v1/feedback rejects product_feedback
      when no verified purchase exists for the given email
    - API returns HTTP 400
    - Error response contains a meaningful detail message
    """

    response = client.post(
        "/v1/feedback",
        data={
            "message_type": "product_feedback",
            "name": "Andrey",
            "email": "unknown_buyer@example.com",
            "subject": "Product feedback",
            "message": "This is a valid feedback message with enough length.",
            "page_url": "http://localhost/product-page",
            "sale_id": "999999",
        },
    )

    assert response.status_code == 400

    data = response.json()

    assert "detail" in data

def test_create_product_feedback_with_verified_purchase(client, db_session):
    """
    Test case: create product feedback with verified purchase

    What we verify:
    - Endpoint /v1/feedback accepts product_feedback
      when a verified purchase exists for the given email and sale_id
    - Response is successful
    - Feedback is stored in the database
    """

    from datetime import datetime, UTC

    from app.models.feedback import FeedbackMessage
    from app.models.product import Product
    from app.models.sale import Sale

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

    sale = Sale(
        product_id=product.id,
        customer_email="buyer@example.com",
        amount=10.00,
        currency="EUR",
        payment_status="paid",
        created_at=datetime.now(UTC),
    )
    db_session.add(sale)
    db_session.commit()

    response = client.post(
        "/v1/feedback",
        data={
            "message_type": "product_feedback",
            "name": "Andrey",
            "email": "buyer@example.com",
            "subject": "Product feedback",
            "message": "This is a valid product feedback message with enough length.",
            "page_url": "http://localhost/product-page",
            "sale_id": str(sale.id),
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "ok"
    assert "id" in data

    saved_feedback = db_session.query(FeedbackMessage).filter_by(id=data["id"]).first()

    assert saved_feedback is not None
    assert saved_feedback.email == "buyer@example.com"
    assert saved_feedback.subject == "Product feedback"

def test_create_general_feedback_empty_message(client):
    """
    Test case: create general feedback with empty message

    What we verify:
    - Endpoint /v1/feedback rejects empty message
    - API returns validation error (422)
    """

    response = client.post(
        "/v1/feedback",
        data={
            "message_type": "general_question",
            "name": "Andrey",
            "email": "andrey@example.com",
            "subject": "Test subject",
            "message": "",
            "page_url": "http://localhost/test-page",
        },
    )

    print(response.json())

    assert response.status_code == 422
