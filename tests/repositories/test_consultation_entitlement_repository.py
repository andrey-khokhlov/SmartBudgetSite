from app.models.consultation_entitlement import ConsultationEntitlement
from app.repositories.consultation_entitlement_repository import (
    ConsultationEntitlementRepository,
)
from tests.services.test_consultation_entitlement_service import (
    create_test_consultation_entitlement,
)


def test_get_by_provider_event_uri_returns_matching_entitlement(db_session):
    """
    Test case: repository resolves entitlement by provider event URI.

    What we verify:
    - Repository returns the correct entitlement.
    - Lookup works using provider_event_uri.
    - Returned entitlement matches persisted booking metadata.
    """

    entitlement = create_test_consultation_entitlement(db_session)

    entitlement.provider_event_uri = (
        "https://api.calendly.com/scheduled_events/test-event"
    )

    db_session.flush()

    result = ConsultationEntitlementRepository.get_by_provider_event_uri(
        db=db_session,
        provider_event_uri=(
            "https://api.calendly.com/scheduled_events/test-event"
        ),
    )

    assert result is not None
    assert isinstance(result, ConsultationEntitlement)
    assert result.id == entitlement.id


def test_get_by_provider_event_uri_returns_none_for_unknown_event(
    db_session,
):
    """
    Test case: repository returns None for unknown provider event URI.

    What we verify:
    - Repository safely returns None.
    - Unknown provider event does not raise exceptions.
    """

    result = (
        ConsultationEntitlementRepository.get_by_provider_event_uri(
            db=db_session,
            provider_event_uri=(
                "https://api.calendly.com/scheduled_events/unknown-event"
            ),
        )
    )

    assert result is None
