import pytest
import json
from pathlib import Path

from app.services.webhooks.payload_normalizers.calendly_payload_normalizer import (
    normalize_calendly_invitee_created_event,
)


def test_normalize_calendly_invitee_created_event():
    """
    Test case: Calendly payload normalization from fixture.
    """

    fixture_path = (
            Path(__file__).parent.parent.parent
            / "fixtures"
            / "calendly"
            / "invitee_created_real_sample.json"
    )

    with open(fixture_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    normalized = normalize_calendly_invitee_created_event(payload)

    assert normalized.provider == "calendly"

    assert (
        normalized.provider_event_uri
        == "https://api.calendly.com/scheduled_events/EVENT_UUID"
    )

    assert (
        normalized.provider_invitee_uri
        == "https://api.calendly.com/scheduled_events/EVENT_UUID/invitees/INVITEE_UUID"
    )


def test_normalize_calendly_invitee_created_event_missing_event_uri():
    """
    Test case: Calendly payload missing required event URI

    What we verify:
    - Normalizer rejects malformed provider payloads.
    - Missing required provider identifiers raise KeyError.

    Business rule:
    - Lifecycle services must never receive incomplete normalized events.
    """

    payload = {
        "payload": {
            "event": {},
            "invitee": {
                "uri": "https://api.calendly.com/invitees/XYZ",
            },
        },
    }

    with pytest.raises(KeyError):
        normalize_calendly_invitee_created_event(payload)


def test_normalize_calendly_invitee_created_event_accepts_string_uri_shape():
    """
    Test case: Calendly payload with direct string URI fields.

    What we verify:
    - Normalizer supports provider payloads where URI fields
      are delivered as plain strings.

    Business rule:
    - Webhook normalization must tolerate provider payload
      shape variations without breaking lifecycle processing.
    """

    payload = {
        "payload": {
            "event": "https://api.calendly.com/scheduled_events/ABC",
            "invitee": "https://api.calendly.com/invitees/XYZ",
        },
    }

    normalized = normalize_calendly_invitee_created_event(payload)

    assert (
        normalized.provider_event_uri
        == "https://api.calendly.com/scheduled_events/ABC"
    )

    assert (
        normalized.provider_invitee_uri
        == "https://api.calendly.com/invitees/XYZ"
    )
