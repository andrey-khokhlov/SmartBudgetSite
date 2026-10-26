from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.feedback import FeedbackMessage
from app.models.product import Product


def create_product(
    db_session,
    *,
    slug: str = "smartbudget-int-standard",
    name: str = "SmartBudget",
) -> Product:
    product = Product(
        family_slug="smartbudget",
        slug=slug,
        name=name,
        edition="Standard",
        status="in_sale",
        archive_path="test/path.zip",
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


def create_feedback(
    db_session,
    product: Product,
    *,
    subject: str,
    message: str,
    name: str | None = "Public author",
    admin_reply: str | None = "Public reply",
    message_type: str = "product_feedback",
    is_published: bool = True,
    published_at: datetime | None = None,
) -> FeedbackMessage:
    feedback = FeedbackMessage(
        type=message_type,
        name=name,
        email="private-customer@example.test",
        subject=subject,
        message=message,
        page_url="https://private.example.test/customer-context",
        user_agent="Private Browser Signature",
        support_reference="DL-PRIVATE",
        admin_reply=admin_reply,
        is_published=is_published,
        published_at=published_at or datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
        reply_sent_to_email="private-reply@example.test",
        product_id=product.id,
    )
    db_session.add(feedback)
    db_session.commit()
    db_session.refresh(feedback)
    return feedback


@pytest.mark.parametrize(
    ("query", "document_lang", "page_title", "heading", "message", "action"),
    [
        (
            "",
            "en",
            "User reviews — SmartBudget",
            "No published reviews yet",
            "Published user reviews are not available for this product yet.",
            "Back to SmartBudget",
        ),
        (
            "?lang=ru",
            "ru",
            "Отзывы пользователей — SmartBudget",
            "Опубликованных отзывов пока нет",
            "Для этого продукта пока нет опубликованных отзывов пользователей.",
            "Вернуться к SmartBudget",
        ),
    ],
)
def test_reviews_empty_state_is_complete_localized_html(
    client: TestClient,
    db_session,
    query: str,
    document_lang: str,
    page_title: str,
    heading: str,
    message: str,
    action: str,
) -> None:
    create_product(db_session)

    response = client.get(f"/reviews/smartbudget-int-standard{query}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert f'<html lang="{document_lang}">' in response.text
    assert f"<title>{page_title}</title>" in response.text
    assert response.text.count("<h1") == 1
    assert heading in response.text
    assert message in response.text
    assert action in response.text
    assert 'href="/products/smartbudget"' in response.text
    assert 'class="site-header"' in response.text
    assert 'class="site-footer"' in response.text


def test_one_published_review_renders_only_public_fields(
    client: TestClient,
    db_session,
) -> None:
    product = create_product(db_session)
    create_feedback(
        db_session,
        product,
        subject="A useful planning tool",
        message="The forecast helped me reconsider a planned purchase.",
        name="Alex",
        admin_reply="Thank you for sharing your experience.",
    )

    response = client.get("/reviews/smartbudget-int-standard")

    assert response.status_code == 200
    assert response.text.count('class="review-card"') == 1
    assert "A useful planning tool" in response.text
    assert "The forecast helped me reconsider a planned purchase." in response.text
    assert "Alex" in response.text
    assert "Thank you for sharing your experience." in response.text
    assert "01.07.2026" in response.text
    assert "private-customer@example.test" not in response.text
    assert "private-reply@example.test" not in response.text
    assert "https://private.example.test/customer-context" not in response.text
    assert "Private Browser Signature" not in response.text
    assert "DL-PRIVATE" not in response.text
    assert "product_id" not in response.text
    assert "is_published" not in response.text


def test_multiple_published_reviews_render_as_separate_articles(
    client: TestClient,
    db_session,
) -> None:
    product = create_product(db_session)
    create_feedback(
        db_session,
        product,
        subject="Older review",
        message="Older public message.",
        published_at=datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
    )
    create_feedback(
        db_session,
        product,
        subject="Newer review",
        message="Newer public message.",
        published_at=datetime(2026, 7, 2, 10, 0, tzinfo=UTC),
    )

    response = client.get("/reviews/smartbudget-int-standard")

    assert response.status_code == 200
    assert response.text.count('class="review-card"') == 2
    assert response.text.count('role="listitem"') == 2
    assert response.text.index("Newer review") < response.text.index("Older review")


def test_unpublished_ineligible_and_other_product_feedback_are_excluded(
    client: TestClient,
    db_session,
) -> None:
    product = create_product(db_session)
    other_product = create_product(
        db_session,
        slug="smartbudget-other",
        name="SmartBudget Other",
    )
    create_feedback(
        db_session,
        product,
        subject="Visible review",
        message="Visible public message.",
    )
    create_feedback(
        db_session,
        product,
        subject="Unpublished review",
        message="Unpublished private message.",
        is_published=False,
    )
    create_feedback(
        db_session,
        product,
        subject="Private question",
        message="Private question message.",
        message_type="general_question",
    )
    create_feedback(
        db_session,
        other_product,
        subject="Other product review",
        message="Other product message.",
    )

    response = client.get("/reviews/smartbudget-int-standard")

    assert response.status_code == 200
    assert "Visible review" in response.text
    assert "Unpublished review" not in response.text
    assert "Unpublished private message." not in response.text
    assert "Private question" not in response.text
    assert "Private question message." not in response.text
    assert "Other product review" not in response.text
    assert "Other product message." not in response.text


def test_anonymous_review_uses_localized_public_fallback(
    client: TestClient,
    db_session,
) -> None:
    product = create_product(db_session)
    create_feedback(
        db_session,
        product,
        subject="Anonymous review",
        message="Public anonymous message.",
        name=None,
    )

    response = client.get("/reviews/smartbudget-int-standard?lang=ru")

    assert response.status_code == 200
    assert "Анонимно" in response.text


@pytest.mark.parametrize("lang,package", [("ru", "ru"), ("en", "int")])
@pytest.mark.parametrize("language_source", ["query", "cookie", "landing"])
def test_default_reviews_navigation_preserves_language_and_sku_ownership(
    client: TestClient,
    db_session,
    lang: str,
    package: str,
    language_source: str,
) -> None:
    for variant in ("ru", "int"):
        product = create_product(db_session, slug=f"smartbudget-{variant}-standard")
        create_feedback(
            db_session,
            product,
            subject=f"Review for {variant}",
            message=f"Only the {variant} SKU owns this review.",
        )

    params = {}
    if language_source == "cookie":
        client.cookies.set("sb_lang", lang)
    else:
        client.cookies.set("sb_lang", "en" if lang == "ru" else "ru")
        if language_source == "landing":
            landing = client.get(f"/products/smartbudget?lang={lang}")
            assert landing.status_code == 200
            assert 'href="/reviews"' in landing.text
        else:
            params = {"lang": lang}

    redirect_response = client.get("/reviews", params=params, follow_redirects=False)

    assert redirect_response.status_code == 307
    assert redirect_response.headers["location"] == (
        f"/reviews/smartbudget-{package}-standard?lang={lang}"
    )
    reviews_response = client.get(redirect_response.headers["location"])
    assert reviews_response.status_code == 200
    assert f'<html lang="{lang}">' in reviews_response.text
    assert f"Review for {package}" in reviews_response.text
    other_package = "int" if package == "ru" else "ru"
    assert f"Review for {other_package}" not in reviews_response.text


@pytest.mark.parametrize("package", ["ru", "int"])
def test_sku_reviews_empty_back_link_returns_to_family(client, db_session, package):
    create_product(db_session, slug=f"smartbudget-{package}-standard")

    response = client.get(f"/reviews/smartbudget-{package}-standard")

    assert response.status_code == 200
    assert 'class="reviews-action" href="/products/smartbudget"' in response.text
    assert client.get("/products/smartbudget").status_code == 200


def test_reviews_database_failure_uses_safe_public_error_response(
    client: TestClient,
    db_session,
    monkeypatch,
) -> None:
    create_product(db_session)

    def fail_review_lookup(*args, **kwargs):
        raise RuntimeError("private database exception detail")

    monkeypatch.setattr("app.web.routes.list_public_reviews", fail_review_lookup)

    with TestClient(app, raise_server_exceptions=False) as safe_client:
        response = safe_client.get("/reviews/smartbudget-int-standard")

    assert response.status_code == 500
    assert "private database exception detail" not in response.text
