from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.service_addon import ServiceAddon


def test_service_addon_can_be_created(db_session):
    """
    Test case: service add-on creation

    What we verify:
    - Service add-on can be linked to product family.
    - Service add-on can be linked to market package.
    - Price and currency are stored separately.
    """

    addon = ServiceAddon(
        code="smartbudget_int_consultation_1h_test",
        name="1:1 Consultation",
        service_type="consultation",
        usage_type="addon",
        family_slug="smartbudget",
        package_code="INT",
        currency_code="EUR",
        amount=Decimal("35.00"),
        is_active=True,
    )

    db_session.add(addon)
    db_session.commit()

    saved_addon = (
        db_session.query(ServiceAddon)
        .filter(ServiceAddon.code == "smartbudget_int_consultation_1h_test")
        .one()
    )

    assert saved_addon.family_slug == "smartbudget"
    assert saved_addon.package_code == "INT"
    assert saved_addon.currency_code == "EUR"
    assert saved_addon.amount == Decimal("35.00")
    assert saved_addon.is_active is True


def test_service_addon_code_must_be_unique(db_session):
    """
    Test case: service add-on code uniqueness

    What we verify:
    - Service add-on code is a stable unique business identifier.
    """

    addon_1 = ServiceAddon(
        code="duplicate_consultation_code",
        name="1:1 Consultation",
        service_type="consultation",
        usage_type="addon",
        family_slug="smartbudget",
        package_code="INT",
        currency_code="EUR",
        amount=Decimal("35.00"),
        is_active=True,
    )

    addon_2 = ServiceAddon(
        code="duplicate_consultation_code",
        name="1:1 Consultation Duplicate",
        service_type="consultation",
        usage_type="addon",
        family_slug="smartbudget",
        package_code="INT",
        currency_code="EUR",
        amount=Decimal("35.00"),
        is_active=True,
    )

    db_session.add(addon_1)
    db_session.commit()

    db_session.add(addon_2)

    with pytest.raises(IntegrityError):
        db_session.commit()
