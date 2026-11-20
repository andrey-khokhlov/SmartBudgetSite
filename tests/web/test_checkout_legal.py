import re
from datetime import date
from xml.etree import ElementTree

import pytest

from app.core.config import settings
from tests.web.test_checkout_initiation import create_checkout_catalog
from tests.web.test_public_consultations import seed_consultations

COPY = {
    "ru": {
        "heading": "Условия покупки и возврата",
        "product": (
            "Вы можете получить полный возврат стоимости SmartBudget в течение "
            "14 календарных дней с момента подтверждения оплаты."
        ),
        "consultation": (
            "Вы можете отменить консультацию до начала её проведения и получить полный "
            "возврат стоимости услуги. Условия после начала консультации и порядок "
            "обращения указаны в Политике возвратов."
        ),
        "policy": "Политика возвратов",
        "seller": "Юридическая информация",
    },
    "en": {
        "heading": "Purchase and Refund Terms",
        "product": (
            "You can receive a full refund for SmartBudget within 14 calendar days "
            "of payment confirmation."
        ),
        "consultation": (
            "You can cancel your consultation before it starts and receive a full refund "
            "of the amount paid for the service. The terms applicable after a consultation "
            "has started and the refund request procedure are described in the Refund Policy."
        ),
        "policy": "Refund Policy",
        "seller": "Legal Information",
    },
}


@pytest.fixture(params=["product", "consultation"])
def checkout(request, db_session):
    if request.param == "product":
        create_checkout_catalog(
            db_session,
            slug="smartbudget-int-standard",
            with_release=False,
            with_offer=False,
        )
        return request.param, "/checkout/smartbudget-int-standard"
    offer_id = seed_consultations(db_session)["EUR"]
    return request.param, f"/consultations/checkout/{offer_id}"


@pytest.mark.parametrize("lang", ["ru", "en"])
@pytest.mark.parametrize("has_policy_date", [True, False])
@pytest.mark.parametrize("has_seller_details", [True, False])
def test_checkout_legal_summary_and_available_links(
    client, checkout, monkeypatch, lang, has_policy_date, has_seller_details
):
    monkeypatch.setattr(
        settings,
        "REFUND_POLICY_PUBLICATION_DATE",
        date(2000, 1, 2) if has_policy_date else None,
    )
    monkeypatch.setattr(settings, "SELLER_ADDRESS_RU", "Учебный адрес")
    monkeypatch.setattr(settings, "SELLER_ADDRESS_EN", "Fictional Seller Address")
    monkeypatch.setattr(
        settings,
        "SELLER_CONTACT_PHONE",
        "+1 202-555-0147" if has_seller_details else "",
    )
    purchase, path = checkout
    response = client.get(path, params={"lang": lang, "currency": "EUR"})
    assert response.status_code == 200
    assert f'<html lang="{lang}">' in response.text
    assert f'method="post" action="{path}?lang={lang}"' in response.text

    markup = re.search(
        r'<section class="checkout-legal".*?</section>', response.text, re.S
    )
    assert markup is not None
    disclosure = ElementTree.fromstring(markup[0])
    copy = COPY[lang]
    assert disclosure.findtext("h2") == copy["heading"]
    assert disclosure.findtext("p") == copy[purchase]
    links = {}
    if has_seller_details:
        if has_policy_date:
            links["/legal/refund-policy"] = copy["policy"]
        links["/legal/seller-information"] = copy["seller"]
    actual_links = disclosure.findall(".//a")
    assert [(link.attrib["href"], link.text) for link in actual_links] == list(
        links.items()
    )
    assert (disclosure.find("ul") is not None) is bool(links)
    for href in links:
        target = client.get(href)
        assert target.status_code == 200
        assert f'<html lang="{lang}">' in target.text
