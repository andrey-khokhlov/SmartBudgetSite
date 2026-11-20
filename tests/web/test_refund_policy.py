import re
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.core.i18n import COOKIE_NAME

PATH = "/legal/refund-policy"
SELLER_PATH = "/legal/seller-information"
PUBLICATION_DATE = date(2000, 1, 2)
TITLES = {
    "ru": "SmartBudget — Политика отмены и возвратов",
    "en": "SmartBudget — Cancellation and Refund Policy",
}
FOOTER_LABELS = {
    "ru": ("Политика возвратов", "Юридическая информация", "Написать в поддержку"),
    "en": ("Refund Policy", "Legal Information", "Contact Support"),
}
SECTION_7_AMENDMENTS = {
    "ru": (
        "Необходимость отдельного согласия на немедленное предоставление цифрового продукта "
        "определяется применимым законодательством. Это не ограничивает добровольное право "
        "на полный возврат стоимости SmartBudget в течение 14 календарных дней, "
        "предусмотренное разделом 2 настоящей Политики."
    ),
    "en": (
        "Whether separate consent is required for immediate digital product delivery depends "
        "on applicable law. This does not limit the voluntary right to a full SmartBudget "
        "refund within 14 calendar days, as described in Section 2 of this Policy."
    ),
}


@pytest.fixture
def policy_configured(monkeypatch):
    monkeypatch.setattr(settings, "REFUND_POLICY_PUBLICATION_DATE", PUBLICATION_DATE)
    monkeypatch.setattr(settings, "SELLER_ADDRESS_RU", "Учебный адрес")
    monkeypatch.setattr(settings, "SELLER_ADDRESS_EN", "Fictional Seller Address")
    monkeypatch.setattr(settings, "SELLER_CONTACT_PHONE", "+1 202-555-0147")


def approved_policy_blocks(lang):
    source = (
        Path(__file__).resolve().parents[2] / "docs" / "release_uiux_requirements.md"
    ).read_text(encoding="utf-8")
    appendix = source.split(
        "\n## Appendix B — Approved Refund Policy publication candidate\n"
    )[1]
    appendix = appendix.split("\n## ", 1)[0]
    locale = appendix.split(f"\n### {TITLES[lang]}\n")[1].split("\n### ", 1)[0]
    body = locale[locale.index("#### 1. ") :]
    blocks = []
    for line in filter(None, body.splitlines()):
        if line.startswith("##### "):
            blocks.append(("h3", line[6:]))
        elif line.startswith("#### "):
            blocks.append(("h2", line[5:]))
        else:
            plain = re.sub(r"\[([^\]]+)\]\(/[^)]+\)", r"\1", line).replace("**", "")
            blocks.append(("p", plain))
    return blocks


def policy_article(html):
    article = re.search(
        r'<article class="refund-policy"[^>]*>.*?</article>', html, re.S
    )
    assert article is not None
    return ElementTree.fromstring(article[0])


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_complete_policy_matches_approved_appendix_b(client, policy_configured, lang):
    response = client.get(PATH, params={"lang": lang})
    assert response.status_code == 200
    assert f'<html lang="{lang}">' in response.text
    assert f"<title>{TITLES[lang]}</title>" in response.text
    assert "[дата публикации]" not in response.text
    assert "[publication date]" not in response.text

    article = policy_article(response.text)
    assert article.findtext("h1") == TITLES[lang]
    updated_label = article.findtext("p/strong")
    assert updated_label == (
        "Последнее обновление:" if lang == "ru" else "Last updated:"
    )
    time = article.find("p/time")
    assert time.attrib == {"datetime": PUBLICATION_DATE.isoformat()}
    assert time.text == PUBLICATION_DATE.isoformat()
    assert [child.tag for child in article] == ["h1", "p", *(["section"] * 9)]
    sections = article.findall("section")
    assert [section.findtext("h2").split(".", 1)[0] for section in sections] == [
        str(number) for number in range(1, 10)
    ]
    assert [
        (block.tag, "".join(block.itertext()))
        for section in sections
        for block in section
    ] == approved_policy_blocks(lang)
    assert SECTION_7_AMENDMENTS[lang] in [p.text for p in sections[6].findall("p")]

    emphasized = {strong.text for strong in article.iter("strong")}
    if lang == "ru":
        assert (
            "Вы можете получить полный возврат стоимости SmartBudget без объяснения причин "
            "в течение 14 календарных дней с момента подтверждения оплаты."
        ) in emphasized
        assert (
            "Вы можете отказаться от консультации до начала её проведения и получить полный "
            "возврат оплаченной стоимости услуги."
        ) in emphasized
        assert {"2 рабочих дней", "5 рабочих дней", "до 10 рабочих дней"} <= emphasized
    else:
        assert (
            "You may request a full refund of your SmartBudget purchase without giving a "
            "reason within 14 calendar days of payment confirmation."
        ) in emphasized
        assert (
            "You may cancel your consultation before it begins and receive a full refund "
            "of the amount paid for the service."
        ) in emphasized
        assert {"2 business days", "5 business days", "10 business days"} <= emphasized


@pytest.mark.parametrize(("lang", "other"), [("ru", "en"), ("en", "ru")])
def test_policy_navigation_and_internal_links(client, policy_configured, lang, other):
    policy_label, seller_label, support_label = FOOTER_LABELS[lang]
    home = client.get("/", params={"lang": lang})
    assert f'href="{PATH}">{policy_label}</a>' in home.text

    response = client.get(PATH)
    assert response.status_code == 200
    assert f'<html lang="{lang}">' in response.text
    assert f'href="{PATH}" aria-current="page">{policy_label}</a>' in response.text
    assert f'href="{SELLER_PATH}">{seller_label}</a>' in response.text
    assert f'href="mailto:support@neocitrix.com">{support_label}</a>' in response.text

    article = policy_article(response.text)
    links = [link.attrib for link in article.iter("a")]
    assert links == [
        {"href": "/refund-request"},
        {"href": SELLER_PATH},
        {"href": "/feedback"},
        {"href": "/refund-request"},
    ]
    for link in links[:3]:
        target = client.get(link["href"])
        assert target.status_code == 200
        assert f'<html lang="{lang}">' in target.text

    switch = re.search(r'href="(\?lang=' + other + r')"', response.text)
    assert switch is not None
    switched = client.get(f"{PATH}{switch[1]}")
    assert switched.status_code == 200
    assert switched.cookies[COOKIE_NAME] == other
    assert f"<title>{TITLES[other]}</title>" in switched.text
    assert f"<title>{TITLES[other]}</title>" in client.get(PATH).text


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("REFUND_POLICY_PUBLICATION_DATE", None),
        ("SELLER_ADDRESS_RU", ""),
        ("SELLER_ADDRESS_EN", " "),
        ("SELLER_CONTACT_PHONE", ""),
    ],
)
def test_unpublished_policy_has_no_route_or_footer_link(
    client, policy_configured, monkeypatch, field, value
):
    monkeypatch.setattr(settings, field, value)
    for lang in ("ru", "en"):
        response = client.get(PATH, params={"lang": lang})
        assert response.status_code == 404
        assert response.json() == {"detail": "Not Found"}
        home = client.get("/", params={"lang": lang})
        assert home.status_code == 200
        assert PATH not in home.text
        assert (SELLER_PATH in home.text) == settings.seller_information_available


def test_policy_does_not_render_request_or_seller_data(
    client, policy_configured, monkeypatch
):
    sample = "<em>Test contact data & markup</em>"
    monkeypatch.setattr(settings, "SELLER_ADDRESS_EN", sample)
    monkeypatch.setattr(settings, "SELLER_CONTACT_PHONE", sample)
    response = client.get(PATH, params={"lang": "en", "publication_date": sample})
    assert response.status_code == 200
    assert "Test contact data" not in response.text
    article = policy_article(response.text)
    assert {item.tag for item in article.iter()} == {
        "article",
        "h1",
        "h2",
        "h3",
        "p",
        "time",
        "section",
        "strong",
        "a",
    }
    assert article.findtext("p/time") == PUBLICATION_DATE.isoformat()


@pytest.mark.parametrize(
    ("raw_date", "expected"),
    [("", None), (" \t ", None), ("2000-01-02", PUBLICATION_DATE)],
)
def test_optional_publication_date_from_environment(monkeypatch, raw_date, expected):
    monkeypatch.setenv("REFUND_POLICY_PUBLICATION_DATE", raw_date)
    assert Settings(_env_file=None).REFUND_POLICY_PUBLICATION_DATE == expected


@pytest.mark.parametrize("raw_date", ["2000-02-30", "20000102", "[publication date]"])
def test_invalid_publication_date_fails_settings_validation(monkeypatch, raw_date):
    monkeypatch.setenv("REFUND_POLICY_PUBLICATION_DATE", raw_date)
    with pytest.raises(ValidationError, match="REFUND_POLICY_PUBLICATION_DATE"):
        Settings(_env_file=None)
