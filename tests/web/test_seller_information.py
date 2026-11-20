import re

import pytest

from app.core.config import settings
from app.core.i18n import COOKIE_NAME

PATH = "/legal/seller-information"
FICTIONAL_ADDRESSES = {
    "ru": "Вымышленная улица, д. 0, Учебный город",
    "en": "0 Fictional Street, Sample City",
}
FICTIONAL_PHONE = "+1 202-555-0147"


@pytest.fixture
def seller_configured(monkeypatch):
    monkeypatch.setattr(settings, "SELLER_ADDRESS_RU", FICTIONAL_ADDRESSES["ru"])
    monkeypatch.setattr(settings, "SELLER_ADDRESS_EN", FICTIONAL_ADDRESSES["en"])
    monkeypatch.setattr(settings, "SELLER_CONTACT_PHONE", FICTIONAL_PHONE)


@pytest.mark.parametrize(
    ("lang", "other", "title", "name", "tax_status"),
    [
        (
            "ru",
            "en",
            "Сведения о продавце",
            "Хохлов Андрей Александрович",
            "НПД, самозанятый",
        ),
        (
            "en",
            "ru",
            "Seller Information",
            "Andrey Alexandrovich Khokhlov",
            "NPD, self-employed",
        ),
    ],
)
def test_seller_information_uses_site_language_selection(
    client, seller_configured, lang, other, title, name, tax_status
):
    response = client.get(PATH, params={"lang": lang})
    assert response.status_code == 200
    assert f'<html lang="{lang}">' in response.text
    assert f"<title>{title} · SmartBudget</title>" in response.text
    assert name in response.text
    assert tax_status in response.text
    assert FICTIONAL_ADDRESSES[lang] in response.text
    assert FICTIONAL_ADDRESSES[other] not in response.text
    assert FICTIONAL_PHONE in response.text
    assert (
        'href="mailto:support@neocitrix.com">support@neocitrix.com</a>'
        in response.text
    )
    assert response.cookies[COOKIE_NAME] == lang

    switch = re.search(r'href="(\?lang=' + other + r')"', response.text)
    assert switch is not None
    switched = client.get(f"{PATH}{switch[1]}")
    assert switched.status_code == 200
    assert FICTIONAL_ADDRESSES[other] in switched.text
    assert FICTIONAL_ADDRESSES[lang] not in switched.text
    assert FICTIONAL_ADDRESSES[other] in client.get(PATH).text


@pytest.mark.parametrize("path", ["/", "/faq"])
@pytest.mark.parametrize(
    ("lang", "label"), [("ru", "Юридическая информация"), ("en", "Legal Information")]
)
def test_configured_footer_links_to_seller_information_only(
    client, seller_configured, path, lang, label
):
    response = client.get(path, params={"lang": lang})
    assert response.status_code == 200
    assert f'href="{PATH}">{label}</a>' in response.text
    assert response.text.count(f'href="{PATH}"') == 1
    assert all(
        value not in response.text
        for value in (*FICTIONAL_ADDRESSES.values(), FICTIONAL_PHONE)
    )

    legal_page = client.get(PATH)
    assert f'href="{PATH}" aria-current="page">{label}</a>' in legal_page.text
    assert FICTIONAL_ADDRESSES[lang] in legal_page.text


@pytest.mark.parametrize(
    "missing_field", ["SELLER_ADDRESS_RU", "SELLER_ADDRESS_EN", "SELLER_CONTACT_PHONE"]
)
@pytest.mark.parametrize("blank_value", ["", " \t "])
def test_incomplete_configuration_hides_both_locales(
    client, seller_configured, monkeypatch, missing_field, blank_value
):
    monkeypatch.setattr(settings, missing_field, blank_value)
    for locale in ("ru", "en"):
        page = client.get(PATH, params={"lang": locale})
        assert page.status_code == 404
        assert page.json() == {"detail": "Not Found"}
        home = client.get("/", params={"lang": locale})
        assert home.status_code == 200
        assert PATH not in home.text


def test_seller_information_escapes_configured_text(
    client, seller_configured, monkeypatch
):
    address = "<strong>Fictional & sample</strong>"
    phone = "<em>Fictional & sample</em>"
    monkeypatch.setattr(settings, "SELLER_ADDRESS_EN", address)
    monkeypatch.setattr(settings, "SELLER_CONTACT_PHONE", phone)

    response = client.get(PATH, params={"lang": "en"})
    assert response.status_code == 200
    assert address not in response.text
    assert phone not in response.text
    assert "&lt;strong&gt;Fictional &amp; sample&lt;/strong&gt;" in response.text
    assert "&lt;em&gt;Fictional &amp; sample&lt;/em&gt;" in response.text
