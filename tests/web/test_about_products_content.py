import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from app.core.i18n import TRANSLATIONS
from app.products_catalog import PRODUCTS, products_index


class PageContent(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.in_main = False
        self.text = []
        self.blocks = []
        self.images = []
        self.links = []
        self.sections = []
        self.current = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.in_main = True
        if not self.in_main:
            return
        attrs = dict(attrs)
        if tag in {"h1", "h2", "h3", "p", "li", "a"}:
            self.current = {"tag": tag, "text": "", **attrs}
            self.blocks.append(self.current)
            if tag == "a":
                self.links.append(self.current)
        if tag == "img":
            self.images.append(attrs)
        if tag == "section":
            self.sections.append(attrs)

    def handle_endtag(self, tag):
        if self.current and self.current["tag"] == tag:
            self.current = None
        if tag == "main":
            self.in_main = False

    def handle_data(self, text):
        if self.in_main:
            self.text.append(text)
            if self.current is not None:
                self.current["text"] += text


def approved_copy(section, lang):
    source = Path("docs/release_uiux_requirements.md").read_text(encoding="utf-8")
    block = source.split(f"### 5.{section}.", 1)[1].split(f"### 5.{section + 1}.", 1)[0]
    copy = block.split(f"#### {lang.upper()}\n\n", 1)[1]
    copy = copy.split("#### EN", 1)[0].split("**Пометка платформы:**", 1)[0]
    return [p.strip().removeprefix("- ") for p in copy.strip().split("\n\n")]


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_about_preserves_complete_approved_biography_without_old_content(client, lang):
    response = client.get(f"/?lang={lang}")
    assert response.status_code == 200
    page = PageContent(response.text)
    copy = approved_copy(2, lang)
    blocks = [" ".join(block["text"].split()) for block in page.blocks]
    for paragraph in copy:
        assert blocks.count(" ".join(paragraph.split())) == 1
    assert [b["text"] for b in page.blocks if b["tag"] in {"h1", "h2", "h3"}] == [
        copy[i] for i in (0, 6, 14, 15, 17, 19, 21)
    ]
    assert [s["aria-labelledby"] for s in page.sections] == [
        "about-heading",
        "about-story-heading",
        "about-work-heading",
        "about-approach-heading",
    ]
    text = " ".join(page.text)
    assert (
        "Имею профессиональную квалификацию ACCA, ранее обладал статусом FCCA."
        if lang == "ru"
        else "I hold an ACCA qualification and previously held FCCA (Fellow) status."
    ) in text
    assert (
        "я прошёл двухлетнюю программу обучения Full-Stack Developer в GeekBrains."
        if lang == "ru"
        else "I completed a two-year Full-Stack Developer training programme at GeekBrains."
    ) in text
    for key in ("about_p", "about_p2", "about_p3", "about_b1", "about_b2", "about_b3"):
        assert TRANSLATIONS[lang][key] not in text
    assert [image["src"] for image in page.images] == [
        "/static/img/me.jpg",
        "/static/img/analytics.svg",
        "/static/img/automation.svg",
        "/static/img/product.svg",
    ]
    assert all(image.get("alt") == "" for image in page.images[1:])
    assert page.images[0]["src"] == "/static/img/me.jpg"
    assert page.images[0]["alt"]
    assert 'class="hero-bullets"' not in response.text
    assert 'class="features-grid"' not in response.text


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_products_approved_card_is_price_free_and_links_to_landing(client, lang):
    response = client.get(f"/products?lang={lang}")
    assert response.status_code == 200
    page = PageContent(response.text)
    copy = approved_copy(3, lang)
    copy[7] = copy[7].replace(
        "Microsoft Excel",
        (
            "Microsoft Excel для Windows"
            if lang == "ru"
            else "Microsoft Excel for Windows"
        ),
    )
    blocks = [" ".join(block["text"].split()) for block in page.blocks]
    for paragraph in copy:
        assert blocks.count(" ".join(paragraph.split())) == 1
    assert [b["text"] for b in page.blocks if b["tag"] == "li"] == copy[4:7]
    assert len(page.links) == 2
    details = next(
        link for link in page.links if link["href"] == "/products/smartbudget"
    )
    requirements = next(
        link
        for link in page.links
        if link["href"] == "/faq?open=system-requirements#system-requirements-question"
    )
    assert requirements["text"].strip() == (
        "Полные системные требования" if lang == "ru" else "Full System Requirements"
    )
    assert details["text"].strip() == copy[8]
    assert client.get(details["href"]).status_code == 200
    assert not re.search(r"[$€₽]|\b(?:RUB|EUR|USD)\b|\d+[.,]\d{2}", " ".join(page.text))
    assert "/products/smartbudget/buy" not in response.text
    assert 'class="products-section"' not in response.text


def test_product_presentation_fields_are_catalog_driven():
    product = PRODUCTS[0]
    card = products_index()[0]
    for field in (
        "description_key",
        "capabilities_title_key",
        "conditions_key",
        "cta_key",
    ):
        assert card[field] == getattr(product, field)
        assert all(card[field] in TRANSLATIONS[lang] for lang in ("ru", "en"))
    assert len(card["highlights_keys"]) == 3
