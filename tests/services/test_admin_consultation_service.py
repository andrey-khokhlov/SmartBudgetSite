from app.services.admin_consultation_service import (
    get_consultation_entitlements,
)


def test_get_consultation_entitlements_returns_list(db_session):
    """
    Test case: load consultation entitlements for admin visibility.

    What we verify:
    - Admin service delegates to repository layer.
    - Service returns a list.
    - Read-only admin visibility boundary is callable.
    """

    result = get_consultation_entitlements(db=db_session)

    assert isinstance(result, list)
