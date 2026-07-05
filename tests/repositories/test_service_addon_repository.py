from decimal import Decimal

from app.models.service_addon import ServiceAddon
from app.repositories.service_addon_repository import ServiceAddonRepository


def test_get_active_addon_by_family_package_and_type(db_session):
    """
    Test case: get active service add-on

    What we verify:
    - Repository returns active add-on by family_slug, package_code, and service_type.
    - Price is read from DB.
    """

    addon = ServiceAddon(
        code="smartbudget_int_consultation_1h_repo_test",
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

    result = ServiceAddonRepository.get_active_addon(
        db_session,
        family_slug="smartbudget",
        package_code="INT",
        service_type="consultation",
        usage_type="addon",
    )

    assert result is not None
    assert result.code == "smartbudget_int_consultation_1h_repo_test"
    assert result.amount == Decimal("35.00")


def test_get_active_addon_ignores_inactive_addons(db_session):
    """
    Test case: inactive service add-on is ignored

    What we verify:
    - Repository does not return inactive add-ons for checkout.
    """

    addon = ServiceAddon(
        code="smartbudget_int_consultation_1h_inactive_repo_test",
        name="1:1 Consultation",
        service_type="consultation",
        usage_type="addon",
        family_slug="smartbudget",
        package_code="INT",
        currency_code="EUR",
        amount=Decimal("35.00"),
        is_active=False,
    )

    db_session.add(addon)
    db_session.commit()

    result = ServiceAddonRepository.get_active_addon(
        db_session,
        family_slug="smartbudget",
        package_code="INT",
        service_type="consultation",
        usage_type="addon",
    )

    assert result is None
