from datetime import datetime, UTC

from app.schemas.webhooks import NormalizedBookingConfirmedEvent


def invitee_created_at(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        return None
    return result.astimezone(UTC) if result.utcoffset() is not None else None


def _extract_uri(value):
    """
    Extract URI from Calendly payload field.

    Business rules:
    - Calendly webhook payload may provide provider identifiers either
      as plain URI strings or as objects containing a "uri" key.
    - Normalized internal events must always receive plain URI strings.

    Raises:
    - KeyError when required URI is missing.
    - TypeError when payload shape is unsupported.
    """

    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        return value["uri"]

    raise TypeError("Unsupported Calendly URI payload field shape.")


def normalize_calendly_invitee_created_event(
    payload: dict,
) -> NormalizedBookingConfirmedEvent:
    """
    Normalize Calendly invitee.created webhook payload.

    Business rules:
    - Converts provider-specific Calendly payload into
      provider-agnostic internal webhook event.
    - Only normalization logic belongs here.
    - No entitlement lifecycle logic allowed.

    Side effects:
    - None.

    Invariants / restrictions:
    - Expects Calendly invitee.created payload shape.
    - Raises KeyError if required provider fields are missing.
    """

    invitee = payload["payload"]
    uri = _extract_uri(invitee["uri"] if "uri" in invitee else invitee["invitee"])
    if "uri" in invitee and "invitee" in invitee and uri != _extract_uri(invitee["invitee"]):
        raise ValueError("Conflicting Calendly invitee identifiers.")
    tracking = invitee.get("tracking")
    return NormalizedBookingConfirmedEvent(
        provider="calendly",
        provider_event_uri=_extract_uri(invitee["event"]),
        provider_invitee_uri=uri,
        occurred_at=invitee_created_at(invitee.get("created_at")),
        correlation=tracking.get("utm_content") if isinstance(tracking, dict) else None,
        invitee_status=invitee.get("status"),
        old_invitee_uri=invitee.get("old_invitee"),
        new_invitee_uri=invitee.get("new_invitee"),
    )
