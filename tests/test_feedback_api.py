# tests/test_feedback_api.py
from decimal import Decimal
from app.services.product_service import set_product_price


def _empty_filename_multipart(file_content: bytes) -> tuple[bytes, str]:
    boundary = "----WebKitFormBoundaryFeedbackTest"
    fields = {
        "message_type": "purchase_or_download_issue",
        "email": "browser@example.com",
        "subject": "Browser multipart submission",
        "message": "This browser multipart submission has enough message length.",
    }
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode()
        )
    parts.append(
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="files"; filename=""\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + file_content
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


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


def test_create_purchase_or_download_issue_persists_safe_reference_and_email(
    client,
    db_session,
):
    from app.models.feedback import FeedbackMessage

    response = client.post(
        "/v1/feedback",
        data={
            "message_type": "purchase_or_download_issue",
            "email": "customer@example.com",
            "subject": "Download problem",
            "message": "The download page says that my access is unavailable.",
            "support_reference": "DL-ABCDEFGH",
        },
    )

    assert response.status_code == 200
    feedback = db_session.get(FeedbackMessage, response.json()["id"])
    assert feedback is not None
    assert feedback.type == "purchase_or_download_issue"
    assert feedback.email == "customer@example.com"
    assert feedback.support_reference == "DL-ABCDEFGH"


def test_create_purchase_or_download_issue_normalizes_empty_reference(
    client,
    db_session,
):
    from app.models.feedback import FeedbackMessage

    response = client.post(
        "/v1/feedback",
        data={
            "message_type": "purchase_or_download_issue",
            "subject": "Payment question",
            "message": "I need help understanding what happened to my purchase.",
            "support_reference": "   ",
        },
    )

    assert response.status_code == 200
    feedback = db_session.get(FeedbackMessage, response.json()["id"])
    assert feedback is not None
    assert feedback.support_reference is None


def test_create_purchase_or_download_issue_rejects_malformed_reference(client):
    response = client.post(
        "/v1/feedback",
        data={
            "message_type": "purchase_or_download_issue",
            "subject": "Download problem",
            "message": "The download page says that my access is unavailable.",
            "support_reference": "/download/private-token",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid support reference"


def test_create_purchase_or_download_issue_rejects_oversized_reference(client):
    response = client.post(
        "/v1/feedback",
        data={
            "message_type": "purchase_or_download_issue",
            "subject": "Download problem",
            "message": "The download page says that my access is unavailable.",
            "support_reference": "DL-" + ("A" * 100),
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid support reference"


def test_create_feedback_rejects_reference_for_unrelated_type(client):
    response = client.post(
        "/v1/feedback",
        data={
            "message_type": "general_question",
            "subject": "General question",
            "message": "This is a general question with enough message length.",
            "support_reference": "DL-ABCDEFGH",
        },
    )

    assert response.status_code == 400
    assert "only allowed" in response.json()["detail"]


def test_create_feedback_normalizes_browser_empty_file_sentinel(
    client,
    db_session,
):
    from app.models.feedback import FeedbackMessage
    from app.models.feedback_attachment import FeedbackAttachment

    body, content_type = _empty_filename_multipart(b"")

    response = client.post(
        "/v1/feedback",
        content=body,
        headers={"Content-Type": content_type},
    )

    assert response.status_code == 200
    feedback = db_session.get(FeedbackMessage, response.json()["id"])
    assert feedback is not None
    assert feedback.type == "purchase_or_download_issue"
    assert (
        db_session.query(FeedbackAttachment)
        .filter_by(feedback_id=feedback.id)
        .count()
        == 0
    )


def test_create_feedback_persists_valid_named_attachment(client, db_session):
    from app.models.feedback import FeedbackMessage
    from app.models.feedback_attachment import FeedbackAttachment

    file_content = b"%PDF-1.4 test attachment"
    response = client.post(
        "/v1/feedback",
        data={
            "message_type": "general_question",
            "email": "attachment@example.com",
            "subject": "Valid attachment",
            "message": "This feedback includes one valid named PDF attachment.",
        },
        files={
            "files": (
                "evidence.pdf",
                file_content,
                "application/pdf",
            )
        },
    )

    assert response.status_code == 200
    feedback = db_session.get(FeedbackMessage, response.json()["id"])
    assert feedback is not None
    attachment = (
        db_session.query(FeedbackAttachment)
        .filter_by(feedback_id=feedback.id)
        .one()
    )
    assert attachment.original_filename == "evidence.pdf"
    assert attachment.content_type == "application/pdf"
    assert attachment.file_size_bytes == len(file_content)


def test_create_feedback_rejects_empty_filename_with_nonzero_content(
    client,
    db_session,
):
    from app.models.feedback import FeedbackMessage

    body, content_type = _empty_filename_multipart(b"not empty")

    response = client.post(
        "/v1/feedback",
        content=body,
        headers={"Content-Type": content_type},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "File must have a filename"
    assert db_session.query(FeedbackMessage).count() == 0
