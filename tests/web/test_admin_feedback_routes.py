from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi.testclient import TestClient

from app.models.feedback import FeedbackMessage
from tests.conftest import auth_client


def test_admin_send_email_route_success_redirects_and_sets_reply_sent(
    auth_client: TestClient,
    db_session: Any,
) -> None:
    """
    Critical route test:
    POST /admin/feedback/{id}/send-email

    Verifies:
    - route is wired correctly
    - redirect happens after success
    - reply_sent_at is set in DB
    """

    feedback = FeedbackMessage(
        type="general_question",
        email="user@example.com",
        subject="Need help",
        message="Please clarify how this works.",
        admin_reply="Thanks, here is the answer.",
        is_resolved=False,
        is_published=False,
    )
    db_session.add(feedback)
    db_session.commit()
    db_session.refresh(feedback)

    response = auth_client.post(
        f"/admin/feedback/{feedback.id}/send-email",
        follow_redirects=False,
    )

    assert response.status_code in (302, 303)
    assert response.headers["location"].startswith(f"/admin/feedback/{feedback.id}")

    db_session.refresh(feedback)

    assert feedback.reply_sent_at is not None
    assert feedback.reply_sent_to_email == "user@example.com"


def test_admin_send_email_route_blocks_second_send_and_does_not_change_reply_sent(
    auth_client: TestClient,
    db_session: Any,
) -> None:
    """
    Critical route test:
    repeated email sending must be blocked.

    Verifies:
    - route is wired to service validation
    - redirect happens after failure
    - existing reply_sent_at is preserved
    """

    original_sent_at = datetime.now().replace(tzinfo=None)

    feedback = FeedbackMessage(
        type="general_question",
        email="user@example.com",
        subject="Need help",
        message="Please clarify how this works.",
        admin_reply="Thanks, here is the answer.",
        is_resolved=False,
        is_published=False,
        reply_sent_at=original_sent_at,
        reply_sent_to_email="user@example.com",
    )
    db_session.add(feedback)
    db_session.commit()
    db_session.refresh(feedback)

    response = auth_client.post(
        f"/admin/feedback/{feedback.id}/send-email",
        follow_redirects=False,
    )

    assert response.status_code in (302, 303)
    assert response.headers["location"] == f"/admin/feedback/{feedback.id}?error=Email%20already%20sent"

    db_session.refresh(feedback)

    assert feedback.reply_sent_at == original_sent_at.replace(tzinfo=None)
    assert feedback.reply_sent_to_email == "user@example.com"


def test_admin_toggle_publish_route_success(
    auth_client: TestClient,
    db_session: Any,
) -> None:
    """
    Critical route test:
    POST /admin/feedback/{id}/toggle-publish

    Verifies:
    - route is wired correctly
    - redirect happens after success
    - publish flag is toggled
    """

    feedback = FeedbackMessage(
        type="product_feedback",
        email="user@example.com",
        subject="Great product",
        message="I really like it.",
        admin_reply="Thanks for your feedback!",
        is_resolved=False,
        is_published=False,
    )
    db_session.add(feedback)
    db_session.commit()
    db_session.refresh(feedback)

    response = auth_client.post(
        f"/admin/feedback/{feedback.id}/publish",
        follow_redirects=False,
    )

    assert response.status_code in (302, 303)
    assert response.headers["location"].startswith(f"/admin/feedback/{feedback.id}")

    db_session.refresh(feedback)

    assert feedback.is_published is True
    assert feedback.published_at is not None


def test_admin_toggle_publish_route_unpublish(
    auth_client: TestClient,
    db_session: Any,
) -> None:
    """
    Critical route test:
    unpublish flow

    Verifies:
    - route is wired correctly
    - redirect happens after success
    - publish flag is toggled back
    """

    feedback = FeedbackMessage(
        type="product_feedback",
        email="user@example.com",
        subject="Great product",
        message="I really like it.",
        admin_reply="Thanks for your feedback!",
        is_resolved=False,
        is_published=True,
        published_at=datetime.now(),
    )
    db_session.add(feedback)
    db_session.commit()
    db_session.refresh(feedback)

    response = auth_client.post(
        f"/admin/feedback/{feedback.id}/publish",
        follow_redirects=False,
    )

    assert response.status_code in (302, 303)
    assert response.headers["location"].startswith(f"/admin/feedback/{feedback.id}")

    db_session.refresh(feedback)

    assert feedback.is_published is False
    assert feedback.published_at is None


def test_admin_feedback_displays_private_support_reference(
    request: Any,
    db_session: Any,
) -> None:
    admin_client: TestClient = request.getfixturevalue("auth_client")
    feedback = FeedbackMessage(
        type="purchase_or_download_issue",
        email="customer@example.com",
        subject="Download problem",
        message="The download is unavailable.",
        support_reference="DL-ABCDEFGH",
        admin_reply="I am checking this.",
        is_resolved=False,
        is_published=False,
    )
    db_session.add(feedback)
    db_session.commit()

    list_response = admin_client.get("/admin/feedback?lang=en")
    detail_response = admin_client.get(f"/admin/feedback/{feedback.id}?lang=en")

    assert list_response.status_code == 200
    assert "Purchase or download issue" in list_response.text
    assert "DL-ABCDEFGH" in list_response.text
    assert detail_response.status_code == 200
    assert "Support reference" in detail_response.text
    assert "DL-ABCDEFGH" in detail_response.text
    assert "Publish Review" not in detail_response.text
