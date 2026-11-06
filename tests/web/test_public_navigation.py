import re
from decimal import Decimal
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urljoin, urlsplit

import pytest

from app.models.product import Product
from app.models.product_price import ProductPrice
from app.models.service_addon import ServiceAddon
from app.services.feedback_prefill_service import DownloadFeedbackPrefillContext
from tests.services.test_consultation_entitlement_service import (
    create_test_consultation_entitlement,
)


class HeaderParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.in_header = False
        self.primary_links = []
        self.segments = []
        self.current_segment = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "header":
            self.in_header = True
        if not self.in_header:
            return
        attributes = dict(attrs)
        classes = attributes.get("class", "").split()
        if "nav-link" in classes:
            self.primary_links.append(attributes)
        if "language-switch__segment" in classes:
            self.current_segment = {"tag": tag, "text": "", **attributes}
            self.segments.append(self.current_segment)

    def handle_data(self, data):
        if self.current_segment is not None:
            self.current_segment["text"] += data

    def handle_endtag(self, tag):
        if self.current_segment is not None and tag == self.current_segment["tag"]:
            self.current_segment = None
        if tag == "header":
            self.in_header = False


@pytest.fixture
def navigation_catalog(db_session):
    products = {}
    for package, currency, amount, addon_amount in [
        ("ru", "RUB", "2990.00", "3900.00"),
        ("int", "EUR", "49.00", "69.00"),
    ]:
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
        db_session.add_all(
            [
                ProductPrice(
                    product_id=product.id,
                    currency_code=currency,
                    amount=Decimal(amount),
                    is_active=True,
                ),
                ServiceAddon(
                    code=f"navigation-consultation-{package}",
                    name="Setup consultation",
                    service_type="consultation",
                    usage_type="addon",
                    family_slug=product.family_slug,
                    package_code=package.upper(),
                    currency_code=currency,
                    amount=Decimal(addon_amount),
                    is_active=True,
                ),
            ]
        )
        products[package] = product
    db_session.commit()
    return products


@pytest.mark.parametrize("lang,alternate", [("ru", "en"), ("en", "ru")])
def test_language_segments_preserve_query_values_and_persist_locale(
    client, lang, alternate
):
    response = client.get(
        "/faq",
        params=[
            ("tag", "first value"),
            ("tag", "second&value"),
            ("empty", ""),
            ("lang", "invalid"),
            ("lang", lang),
        ],
    )
    header = HeaderParser(response.text)
    assert [segment["text"].strip() for segment in header.segments] == ["RU", "EN"]
    current = next(segment for segment in header.segments if segment["lang"] == lang)
    assert current["tag"] == "span"
    assert current["aria-current"] == "true"
    assert "href" not in current
    assert "tabindex" not in current

    link = next(segment for segment in header.segments if segment["lang"] == alternate)
    assert link["tag"] == "a"
    assert "aria-current" not in link
    assert "tabindex" not in link
    target = urlsplit(urljoin(str(response.url), link["href"]))
    assert target.path == "/faq"
    query = parse_qsl(target.query, keep_blank_values=True)
    assert [(key, value) for key, value in query if key != "lang"] == [
        ("tag", "first value"),
        ("tag", "second&value"),
        ("empty", ""),
    ]
    assert [value for key, value in query if key == "lang"] == [alternate]

    switched = client.get(target.geturl())
    assert switched.status_code == 200
    assert switched.context["lang"] == alternate
    assert f"sb_lang={alternate};" in switched.headers["set-cookie"]
    assert client.get("/products").context["lang"] == alternate


@pytest.mark.parametrize("path", ["/", "/products", "/faq", "/feedback"])
@pytest.mark.parametrize(
    "lang,feedback_label", [("en", "Feedback"), ("ru", "Обратная связь")]
)
def test_shared_footer_has_only_approved_links(client, path, lang, feedback_label):
    response = client.get(path, params={"lang": lang})
    assert response.status_code == 200
    footer = re.search(r"<footer\b[^>]*>(.*?)</footer>", response.text, re.S)
    assert footer is not None
    assert "© Andrey Khokhlov" in footer[1]
    assert re.findall(r'<a\b[^>]*\bhref="([^"]+)"[^>]*>(.*?)</a>', footer[1], re.S) == [
        ("/faq", "FAQ"),
        ("/feedback", feedback_label),
        ("mailto:support@neocitrix.com", "support@neocitrix.com"),
    ]


@pytest.mark.parametrize("lang,alternate", [("ru", "en"), ("en", "ru")])
@pytest.mark.parametrize("package,currency", [("ru", "RUB"), ("int", "EUR")])
@pytest.mark.parametrize("consultation", [None, "0", "1"])
def test_checkout_language_switch_preserves_exact_order_composition(
    client, navigation_catalog, lang, alternate, package, currency, consultation
):
    product = navigation_catalog[package]
    params = {"currency": currency, "lang": lang, "source": "header test"}
    if consultation is not None:
        params["consultation"] = consultation
    response = client.get(f"/checkout/{product.slug}", params=params)
    assert response.status_code == 200
    link = next(
        segment
        for segment in HeaderParser(response.text).segments
        if segment["tag"] == "a"
    )
    target = urljoin(str(response.url), link["href"])
    assert urlsplit(target).path == f"/checkout/{product.slug}"
    assert dict(parse_qsl(urlsplit(target).query)) == {**params, "lang": alternate}

    switched = client.get(target)
    assert switched.status_code == 200
    assert "Currency is required" not in switched.text
    assert switched.context["lang"] == alternate
    assert switched.context["product"].id == product.id
    assert switched.context["package"] == response.context["package"]
    assert switched.context["price"].id == response.context["price"].id
    assert switched.context["price"].currency_code == currency
    assert switched.context["total_amount"] == response.context["total_amount"]
    assert switched.context["consultation"] == (consultation == "1")
    if consultation == "1":
        assert switched.context["addon"].id == response.context["addon"].id
    else:
        assert switched.context["addon"] is None
    assert f'name="currency" value="{currency}"' in switched.text
    assert (
        f'name="consultation" value="{1 if consultation == "1" else 0}"'
        in switched.text
    )


@pytest.mark.parametrize(
    "path,current_href,status",
    [
        ("/", "/", 200),
        ("/products", "/products", 200),
        ("/products/smartbudget", "/products", 200),
        ("/products/smartbudget/buy", "/products", 200),
        ("/checkout/smartbudget-int-standard?currency=EUR", "/products", 200),
        ("/faq", None, 200),
        ("/feedback", None, 200),
        ("/reviews/smartbudget-int-standard", None, 200),
        ("/download/missing-token", None, 404),
        ("/consultation/book/missing-token", None, 404),
        ("/payment/result", None, 200),
    ],
)
def test_primary_navigation_marks_only_the_current_section(
    client, navigation_catalog, path, current_href, status
):
    response = client.get(path)
    assert response.status_code == status
    links = HeaderParser(response.text).primary_links
    assert [link["href"] for link in links] == ["/", "/products"]
    assert [link["href"] for link in links if link.get("aria-current") == "page"] == (
        [current_href] if current_href else []
    )


@pytest.mark.parametrize("lang,alternate", [("ru", "en"), ("en", "ru")])
def test_successful_booking_persists_language_without_echoing_capability_path(
    client, db_session, lang, alternate
):
    entitlement = create_test_consultation_entitlement(db_session)
    db_session.commit()
    path = f"/consultation/book/{entitlement.booking_token}"
    response = client.get(path, params={"lang": lang})
    assert response.status_code == 200
    assert f"sb_lang={lang};" in response.headers["set-cookie"]
    assert entitlement.booking_token not in response.text
    assert client.get("/faq").context["lang"] == lang
    link = next(
        segment
        for segment in HeaderParser(response.text).segments
        if segment["tag"] == "a"
    )
    assert link["href"] == f"?lang={alternate}"
    switched = client.get(urljoin(str(response.url), link["href"]))
    assert switched.status_code == 200
    assert switched.context["lang"] == alternate
    assert switched.context["entitlement"].id == entitlement.id
    assert client.get("/products").context["lang"] == alternate


def test_feedback_language_switch_preserves_only_resolved_support_context(
    client, monkeypatch
):
    context = DownloadFeedbackPrefillContext(
        message_type="purchase_or_download_issue",
        customer_email="buyer@example.test",
        support_reference="DL-ABCDEFGH",
        product_name="SmartBudget",
        product_edition="Standard",
        release_version="1.0",
        purchase_date="04.11.2026",
        subject="Download help",
        message="Please help with my download.",
    )
    monkeypatch.setattr(
        "app.web.routes.get_download_feedback_prefill_context",
        lambda *args: context,
    )
    response = client.get(
        "/feedback",
        params={
            "message_type": "purchase_or_download_issue",
            "support_reference": context.support_reference,
            "lang": "en",
        },
    )
    link = next(
        segment
        for segment in HeaderParser(response.text).segments
        if segment["tag"] == "a"
    )
    assert dict(parse_qsl(urlsplit(link["href"]).query)) == {
        "message_type": "purchase_or_download_issue",
        "support_reference": context.support_reference,
        "lang": "ru",
    }
    assert context.customer_email not in link["href"]
    switched = client.get(urljoin(str(response.url), link["href"]))
    assert switched.status_code == 200
    assert (
        switched.context["prefill_context"].support_reference
        == context.support_reference
    )
