from decimal import Decimal
from uuid import UUID

import pytest

from app.models.product import Product
from app.models.service_addon import ServiceAddon
from app.services.consultation_offer_admin_service import (
    ConsultationOfferInputError,
    create_consultation_offer,
    update_consultation_offer,
)


@pytest.fixture()
def product_family(db_session):
    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-int-standard-offer-admin-test",
        name="SmartBudget",
        edition="Standard",
        archive_path="",
        status="in_development",
    )
    db_session.add(product)
    db_session.commit()
    return product


def create_offer(db_session, **overrides):
    values = {
        "family_slug": "smartbudget",
        "package_code": "INT",
        "service_type": "consultation",
        "usage_type": "addon",
        "currency_code": "EUR",
        "name": "Consultation",
        "amount": Decimal("35.00"),
        "is_active": True,
    }
    values.update(overrides)
    return create_consultation_offer(db_session, **values)


def test_active_create_generates_uuid_and_deactivates_same_identity(
    db_session,
    product_family,
):
    previous = create_offer(db_session)
    current = create_offer(db_session, name="Current", amount=Decimal("50.00"))

    db_session.refresh(previous)
    assert UUID(current.code).version == 4
    assert previous.is_active is False
    assert current.is_active is True


def test_inactive_create_keeps_active_offer(db_session, product_family):
    active = create_offer(db_session)
    historical = create_offer(db_session, name="Historical", is_active=False)

    db_session.refresh(active)
    assert active.is_active is True
    assert historical.is_active is False


def test_activation_deactivates_current_but_not_other_currency_or_usage(
    db_session,
    product_family,
):
    old_eur = create_offer(db_session, name="Old EUR", is_active=False)
    current_eur = create_offer(db_session, name="Current EUR")
    rub = create_offer(db_session, currency_code="RUB", name="RUB")
    standalone = create_offer(db_session, usage_type="standalone", name="Standalone")

    updated = update_consultation_offer(
        db_session,
        offer_id=old_eur.id,
        name="Reactivated EUR",
        amount=Decimal("50.00"),
        is_active=True,
    )

    for offer in (current_eur, rub, standalone):
        db_session.refresh(offer)
    assert updated.is_active is True
    assert current_eur.is_active is False
    assert rub.is_active is True
    assert standalone.is_active is True


def test_update_changes_only_mutable_fields(db_session, product_family):
    offer = create_offer(db_session)
    identity = (
        offer.code,
        offer.family_slug,
        offer.package_code,
        offer.service_type,
        offer.usage_type,
        offer.currency_code,
    )

    updated = update_consultation_offer(
        db_session,
        offer_id=offer.id,
        name="Updated consultation",
        amount=Decimal("50.00"),
        is_active=False,
    )

    assert updated.name == "Updated consultation"
    assert updated.amount == Decimal("50.00")
    assert updated.is_active is False
    assert identity == (
        updated.code,
        updated.family_slug,
        updated.package_code,
        updated.service_type,
        updated.usage_type,
        updated.currency_code,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("family_slug", "invented"),
        ("package_code", "OTHER"),
        ("service_type", "consulting"),
        ("usage_type", "bundle"),
        ("currency_code", "USD"),
    ],
)
def test_create_rejects_unapproved_controlled_values(
    db_session,
    product_family,
    field,
    value,
):
    with pytest.raises(ConsultationOfferInputError):
        create_offer(db_session, **{field: value})

    assert db_session.query(ServiceAddon).count() == 0
