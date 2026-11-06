from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.config import settings
from app.models.consultation_entitlement import ConsultationEntitlement
from app.models.download_entitlement import DownloadEntitlement
from app.models.enums import PaymentStatus, SaleItemType
from app.models.product import Product
from app.models.product_release import ProductRelease
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.service_addon import ServiceAddon
from app.models.service_payment_provider_offer import ServicePaymentProviderOffer
from app.schemas.webhooks import NormalizedPaymentEvent, PaymentOutcome
from app.services.lava_top.client import LavaTopInvoice, LavaTopRequestError
from app.services.payment_provider_offer_service import (
    PaymentProviderOfferInputError,
    set_lava_top_standalone_offer,
)
from app.services.payment_reconciliation_service import (
    PaymentReconciliationMismatchError,
    PaymentReconciliationResult,
    reconcile_payment_event,
)
from app.services.payment_service import (
    CheckoutValidationError,
    PaymentCheckoutError,
    PaymentReconciliationRequiredError,
    initiate_lava_top_standalone_consultation_checkout,
)
from scripts import set_service_payment_provider_offer


def add_offer(db, currency="RUB", **overrides):
    values = {
        "code": f"standalone-{currency}",
        "name": "Initial setup consultation",
        "family_slug": "smartbudget",
        "package_code": "RU" if currency == "RUB" else "INT",
        "currency_code": currency,
        "service_type": "consultation",
        "usage_type": "standalone",
        "amount": Decimal("6123.45" if currency == "RUB" else "101.25"),
        "is_active": True,
    }
    offer = ServiceAddon(**(values | overrides))
    db.add(offer)
    db.commit()
    return offer.id


@pytest.fixture
def configured_offer(db_session):
    offer_id = add_offer(db_session)
    set_lava_top_standalone_offer(
        db_session, service_addon_id=offer_id, external_offer_id="standalone-offer"
    )
    return offer_id


@pytest.fixture
def provider(monkeypatch):
    stub = Mock(return_value=LavaTopInvoice("invoice-1", "https://pay.example/hosted"))
    monkeypatch.setattr("app.services.payment_service.create_invoice", stub)
    return stub


def start(db, offer_id, currency="RUB", email=" BUYER@example.com "):
    return initiate_lava_top_standalone_consultation_checkout(
        db, service_addon_id=offer_id, currency=currency, customer_email=email
    )


@pytest.mark.parametrize(
    "currency,amount", [("RUB", Decimal("6123.45")), ("EUR", Decimal("101.25"))]
)
def test_initiation_snapshots_exact_standalone_offer(
    db_session, provider, currency, amount
):
    offer_id = add_offer(db_session, currency)
    add_offer(
        db_session,
        currency,
        code="discounted-addon",
        usage_type="addon",
        amount=Decimal("30"),
    )
    add_offer(db_session, "EUR" if currency == "RUB" else "RUB")
    set_lava_top_standalone_offer(
        db_session, service_addon_id=offer_id, external_offer_id="standalone-offer"
    )
    assert (
        start(db_session, offer_id, f" {currency.lower()} ")
        == "https://pay.example/hosted"
    )
    provider.assert_called_once_with(
        email="buyer@example.com",
        offer_id="standalone-offer",
        amount=amount,
        currency=currency,
    )
    sale = db_session.query(Sale).one()
    assert sale.product_id is None
    assert (sale.payment_provider, sale.external_payment_id) == (
        "lava_top",
        "invoice-1",
    )
    assert sale.payment_status == PaymentStatus.PENDING
    assert (sale.amount, sale.currency) == (amount, currency)
    (item,) = sale.items
    assert item.item_type == SaleItemType.SERVICE
    assert (item.service_addon_id, item.quantity) == (offer_id, 1)
    assert item.product_id is None and item.product_release_id is None
    assert (item.item_name, item.amount, item.currency_code) == (
        "Initial setup consultation",
        amount,
        currency,
    )
    assert db_session.query(Product).count() == 0
    assert db_session.query(ProductRelease).count() == 0
    assert db_session.query(DownloadEntitlement).count() == 0
    assert db_session.query(ConsultationEntitlement).count() == 0


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "inactive",
        "addon",
        "wrong_type",
        "mismatch",
        "unsupported",
        "zero",
        "email",
        "missing_mapping",
        "other_provider",
    ],
)
def test_invalid_checkout_creates_no_sale_or_invoice(db_session, provider, case):
    overrides = {
        "inactive": {"is_active": False},
        "addon": {"usage_type": "addon"},
        "wrong_type": {"service_type": "support"},
        "zero": {"amount": Decimal("0")},
    }.get(case, {})
    offer_id = -1 if case == "missing" else add_offer(db_session, **overrides)
    if case not in {"missing", "missing_mapping"}:
        db_session.add(
            ServicePaymentProviderOffer(
                service_addon_id=offer_id,
                provider="other" if case == "other_provider" else "lava_top",
                external_offer_id="mapped-offer",
            )
        )
        db_session.commit()
    currency = {"mismatch": "EUR", "unsupported": "USD"}.get(case, "RUB")
    email = "invalid" if case == "email" else "buyer@example.com"
    with pytest.raises(CheckoutValidationError):
        start(db_session, offer_id, currency, email)
    provider.assert_not_called()
    assert db_session.query(Sale).count() == 0


def test_configure_mapping_from_operator_cli(db_session, monkeypatch, capsys, provider):
    offer_id = add_offer(db_session)
    monkeypatch.setattr(
        set_service_payment_provider_offer, "SessionLocal", lambda: db_session
    )
    for external_id, action in [
        (" first ", "created"),
        ("second", "updated"),
        ("second", "unchanged"),
    ]:
        set_service_payment_provider_offer.main(
            ["--service-addon-id", str(offer_id), "--external-offer-id", external_id]
        )
        assert capsys.readouterr().out.startswith(action)
        mapping = db_session.query(ServicePaymentProviderOffer).one()
        assert mapping.external_offer_id == external_id.strip()
    provider.assert_not_called()


def test_configuration_rejects_invalid_target_and_offer_id(db_session):
    addon_id = add_offer(db_session, usage_type="addon")
    standalone_id = add_offer(db_session, code="valid-standalone")
    for offer_id, external_id in [
        (addon_id, "offer"),
        (-1, "offer"),
        (standalone_id, "  "),
        (standalone_id, "x" * 201),
    ]:
        with pytest.raises(PaymentProviderOfferInputError):
            set_lava_top_standalone_offer(
                db_session, service_addon_id=offer_id, external_offer_id=external_id
            )
    assert db_session.query(ServicePaymentProviderOffer).count() == 0


@pytest.mark.parametrize(
    "provider_name,external_id",
    [("lava_top", "different-id"), (" ", "id"), ("other", " ")],
)
def test_mapping_constraints(db_session, configured_offer, provider_name, external_id):
    db_session.add(
        ServicePaymentProviderOffer(
            service_addon_id=configured_offer,
            provider=provider_name,
            external_offer_id=external_id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    assert db_session.query(ServicePaymentProviderOffer).count() == 1


def test_missing_provider_credentials_do_not_contact_provider(
    db_session, configured_offer, monkeypatch
):
    monkeypatch.setattr(settings, "LAVA_TOP_API_KEY", "")
    request = Mock(side_effect=AssertionError("Unexpected provider HTTP call"))
    monkeypatch.setattr("app.services.lava_top.client.httpx.post", request)
    with pytest.raises(PaymentCheckoutError):
        start(db_session, configured_offer)
    request.assert_not_called()
    sale = db_session.query(Sale).one()
    assert sale.payment_status == PaymentStatus.FAILED
    assert sale.external_payment_id is None


def test_provider_failure_keeps_failed_snapshot(db_session, configured_offer, provider):
    provider.side_effect = LavaTopRequestError("provider rejected request")
    with pytest.raises(PaymentCheckoutError):
        start(db_session, configured_offer)
    sale = db_session.query(Sale).one()
    assert sale.payment_status == PaymentStatus.FAILED
    assert sale.external_payment_id is None
    assert sale.items[0].service_addon_id == configured_offer
    assert db_session.query(ConsultationEntitlement).count() == 0


def test_preparation_db_failure_rolls_back_before_provider(
    db_session, configured_offer, provider, monkeypatch
):
    real_flush = db_session.flush

    def fail_item_flush(*args, **kwargs):
        if any(isinstance(obj, SaleItem) for obj in db_session.new):
            raise SQLAlchemyError("could not write service item")
        return real_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", fail_item_flush)
    with pytest.raises(SQLAlchemyError):
        start(db_session, configured_offer)
    provider.assert_not_called()
    assert db_session.query(Sale).count() == 0


def test_invoice_identity_commit_failure_requires_reconciliation(
    db_session, configured_offer, provider, monkeypatch
):
    monkeypatch.setattr(
        db_session, "commit", Mock(side_effect=SQLAlchemyError("commit failed"))
    )
    with pytest.raises(PaymentReconciliationRequiredError) as error:
        start(db_session, configured_offer)
    assert vars(error.value) == {"provider_invoice_id": "invoice-1"}
    assert provider.call_count == 1
    assert db_session.query(Sale).count() == 0


def test_paid_service_only_reconciliation_preserves_snapshot_and_is_idempotent(
    db_session, configured_offer, provider
):
    start(db_session, configured_offer)
    sale = db_session.query(Sale).one()
    db_session.get(ServiceAddon, configured_offer).amount = Decimal("7000.00")
    db_session.commit()
    event = NormalizedPaymentEvent(
        provider="lava_top",
        external_payment_id="invoice-1",
        outcome=PaymentOutcome.SUCCESS,
        amount=Decimal("6123.45"),
        currency="RUB",
    )
    for mismatch in [
        {"provider": "other"},
        {"external_payment_id": "unknown"},
        {"amount": Decimal("7000.00")},
        {"currency": "EUR"},
    ]:
        with pytest.raises(PaymentReconciliationMismatchError):
            reconcile_payment_event(db_session, event.model_copy(update=mismatch))
        assert sale.payment_status == PaymentStatus.PENDING
        assert db_session.query(ConsultationEntitlement).count() == 0

    assert (
        reconcile_payment_event(db_session, event).result
        == PaymentReconciliationResult.APPLIED
    )
    db_session.commit()
    assert (
        reconcile_payment_event(db_session, event).result
        == PaymentReconciliationResult.IDEMPOTENT
    )
    db_session.commit()
    assert sale.payment_status == PaymentStatus.PAID
    (item,) = sale.items
    assert sale.amount == item.amount == event.amount
    assert item.service_addon_id == configured_offer
    assert db_session.query(ConsultationEntitlement).one().sale_item_id == item.id
    assert db_session.query(DownloadEntitlement).count() == 0
