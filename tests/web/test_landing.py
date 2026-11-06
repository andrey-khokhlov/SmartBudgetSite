from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

import pytest
from sqlalchemy import event, text

from app.models.product import Product
from app.models.product_price import ProductPrice

STEMS = [
    "g8_01_savings_breakdown",
    "g8_02_future_expense_warning",
    "g8_03_plan_actual_transition",
    "g8_04_reconciliation_before",
    "g8_05_reconciliation_after",
]


class LandingParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.in_main = False
        self.text = []
        self.images = []
        self.links = []
        self.sections = []
        self.current_link = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.in_main = True
        if not self.in_main:
            return
        attrs = dict(attrs)
        if tag == "section":
            self.sections.append(attrs)
        if tag == "a":
            self.current_link = {**attrs, "images": []}
            self.links.append(self.current_link)
        if tag == "img":
            self.images.append(attrs)
            if self.current_link is not None:
                self.current_link["images"].append(attrs)

    def handle_endtag(self, tag):
        if tag == "a":
            self.current_link = None
        if tag == "main":
            self.in_main = False

    def handle_data(self, data):
        if self.in_main:
            self.text.append(data)


def approved_paragraphs(number, lang):
    source = Path("docs/release_uiux_requirements.md").read_text(encoding="utf-8")
    next_heading = "### 5.2." if number == 7 else f"#### 5.1.{number + 1}."
    block = source.split(f"#### 5.1.{number}.", 1)[1].split(next_heading, 1)[0]
    copy = block.split(f"##### {lang.upper()}\n\n", 1)[1]
    if lang == "ru":
        copy = copy.split("##### EN", 1)[0]
    copy = copy.split("**Подписи к изображению:**", 1)[0]
    copy = copy.split("Текст и смысл подписи выше", 1)[0]
    copy = copy.split("**Обязательное дополнение:**", 1)[0]
    copy = copy.split("Версия 1.0 в этом блоке", 1)[0]
    return [
        paragraph.strip().removeprefix("- ")
        for paragraph in copy.strip().split("\n\n")
        if paragraph.strip()
        not in {"Подпись к изображению", "Image caption", "{{ product_price }}"}
    ]


@pytest.mark.parametrize("lang", ["ru", "en"])
@pytest.mark.parametrize("number", [1, 2, 3, 4, 5, 6, 7])
def test_landing_preserves_approved_copy(client, lang, number):
    response = client.get(f"/products/smartbudget?lang={lang}")
    assert response.status_code == 200
    rendered = " ".join(" ".join(LandingParser(response.text).text).split())
    for paragraph in approved_paragraphs(number, lang):
        if number == 1:
            paragraph = paragraph.replace(
                "Посмотреть возможности SmartBudget",
                "Посмотреть, как работает SmartBudget ↓",
            ).replace("Explore SmartBudget", "See how SmartBudget works ↓")
        assert " ".join(paragraph.split()) in rendered


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_landing_uses_final_localized_original_images_and_demo_anchor(client, lang):
    response = client.get(f"/products/smartbudget?lang={lang}")
    landing = LandingParser(response.text)
    expected = [
        f"/static/img/smartbudget/landing/{lang}/{stem}_{lang}.png" for stem in STEMS
    ]
    assert [image["src"] for image in landing.images] == expected
    assert all(image.get("alt", "").strip() for image in landing.images)
    image_links = [link for link in landing.links if link["images"]]
    assert [link["href"] for link in image_links] == expected
    for link in image_links:
        assert link["target"] == "_blank"
        assert "noopener" in link["rel"].split()
        assert link["aria-label"].strip()
        assert (
            client.get(link["href"]).content == Path("app" + link["href"]).read_bytes()
        )
    hero = next(link for link in landing.links if link["href"] == "#sb-capabilities")
    assert hero["class"] == "sb-hero__explore"
    assert (
        "Посмотреть, как работает SmartBudget ↓"
        if lang == "ru"
        else "See how SmartBudget works ↓"
    ) in " ".join(landing.text)
    assert 'class="sb-image-open"' not in response.text
    assert 'class="sb-image-hint"' not in response.text
    assert [section.get("id") for section in landing.sections] == [
        None,
        "sb-capabilities",
        "sb-future-expense",
        "sb-plan-actual",
        "sb-reconciliation",
        "sb-practical",
        "sb-offer",
    ]
    assert all(
        "sb-consult" not in section.get("class", "") for section in landing.sections
    )
    assert not any(
        "t.me" in link["href"] or "telegram" in link["href"].lower()
        for link in landing.links
    )
    assert "Message me on Telegram" not in " ".join(landing.text)
    assert "Написать в Telegram" not in " ".join(landing.text)
    assert "g8_04_reconciliation_before" in expected[3]
    assert "g8_05_reconciliation_after" in expected[4]


def add_catalog_price(db_session, package, currency, amount, *, active=True):
    product = Product(
        family_slug="smartbudget",
        slug=f"smartbudget-{package}-standard",
        name="SmartBudget",
        edition="Standard",
        archive_path="",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()
    price = ProductPrice(
        product_id=product.id,
        currency_code=currency,
        amount=Decimal(amount),
        is_active=active,
    )
    db_session.add(price)
    return price


@pytest.mark.parametrize(
    "lang,price_text,updated_text",
    [("ru", "3 217,25 RUB", "4 321,75 RUB"), ("en", "73.50 EUR", "4,321.75 EUR")],
)
def test_landing_offer_uses_exact_catalog_price_and_keeps_buy_route(
    client, db_session, lang, price_text, updated_text
):
    prices = {
        "ru": add_catalog_price(db_session, "ru", "RUB", "3217.25"),
        "en": add_catalog_price(db_session, "int", "EUR", "73.50"),
    }
    db_session.commit()
    response = client.get(f"/products/smartbudget?lang={lang}")
    assert response.status_code == 200
    before_offer, offer = response.text.split('id="sb-offer"', 1)
    assert price_text not in before_offer
    assert f'<p class="sb-offer__price">{price_text}</p>' in offer
    other_price = "73.50 EUR" if lang == "ru" else "3 217,25 RUB"
    assert other_price not in offer
    assert "#system-requirements" not in response.text
    assert 'href="/products/smartbudget/buy"' in offer
    assert client.get("/products/smartbudget/buy").status_code == 200

    prices[lang].amount = Decimal("4321.75")
    db_session.commit()
    refreshed = client.get("/products/smartbudget")
    assert refreshed.context["lang"] == lang
    assert f'<p class="sb-offer__price">{updated_text}</p>' in refreshed.text


@pytest.mark.parametrize(
    "condition", ["missing", "inactive", "nonpositive", "ambiguous"]
)
def test_landing_hides_unusable_price_but_keeps_buy_link(client, db_session, condition):
    add_catalog_price(db_session, "int", "EUR", "73.50")
    if condition != "missing":
        price = add_catalog_price(
            db_session,
            "ru",
            "RUB",
            "0.00" if condition == "nonpositive" else "3217.25",
            active=condition != "inactive",
        )
    if condition == "ambiguous":
        db_session.add(
            ProductPrice(
                product_id=price.product_id,
                currency_code="EUR",
                amount=Decimal("73.50"),
            )
        )
    db_session.commit()
    response = client.get("/products/smartbudget?lang=ru")
    assert response.status_code == 200
    assert 'class="sb-offer__price"' not in response.text
    assert 'href="/products/smartbudget/buy"' in response.text


def test_landing_rolls_back_failed_price_query_and_renders(client, monkeypatch):
    rolled_back = []

    def record_rollback(session):
        rolled_back.append(session)

    def fail_price_lookup(repository, slug):
        event.listen(repository.db, "after_rollback", record_rollback)
        repository.db.execute(text("SELECT 1 FROM missing_landing_price_test_table"))

    monkeypatch.setattr(
        "app.web.routes.ProductsRepository.get_product_with_active_price_by_slug",
        fail_price_lookup,
    )

    response = client.get("/products/smartbudget?lang=ru")

    assert len(rolled_back) == 1
    assert response.status_code == 200
    assert 'class="sb-offer__price"' not in response.text
    assert 'href="/products/smartbudget/buy"' in response.text
