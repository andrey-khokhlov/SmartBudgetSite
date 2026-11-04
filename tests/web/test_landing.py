from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

import pytest

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
    block = source.split(f"#### 5.1.{number}.", 1)[1].split(
        f"#### 5.1.{number + 1}.", 1
    )[0]
    copy = block.split(f"##### {lang.upper()}\n\n", 1)[1]
    if lang == "ru":
        copy = copy.split("##### EN", 1)[0]
    copy = copy.split("**Подписи к изображению:**", 1)[0]
    copy = copy.split("Текст и смысл подписи выше", 1)[0]
    return [
        paragraph.strip().removeprefix("- ")
        for paragraph in copy.strip().split("\n\n")
        if paragraph.strip() not in {"Подпись к изображению", "Image caption"}
    ]


@pytest.mark.parametrize("lang", ["ru", "en"])
@pytest.mark.parametrize("number", [1, 2, 3, 4, 5])
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
        None,
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


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_existing_temporary_purchase_tail_reaches_buy_route(client, db_session, lang):
    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-int-standard",
        name="SmartBudget",
        edition="Standard",
        archive_path="",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()
    db_session.add(
        ProductPrice(
            product_id=product.id,
            currency_code="EUR",
            amount=Decimal("49.00"),
            is_active=True,
        )
    )
    db_session.commit()
    response = client.get(f"/products/smartbudget?lang={lang}")
    links = LandingParser(response.text).links
    buy = next(link for link in links if link["href"] == "/products/smartbudget/buy")
    assert client.get(buy["href"]).status_code == 200
