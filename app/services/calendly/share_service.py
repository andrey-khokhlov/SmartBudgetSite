import base64
import hmac
import re
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.consultation_entitlement import ConsultationEntitlement
from app.repositories.consultation_entitlement_repository import (
    ConsultationEntitlementRepository,
)
from app.services.calendly.calendly_api_client import (
    CALENDLY_API_BASE_URL,
    CalendlyAPIError,
    create_share,
    find_share,
    resource_path,
)
from app.services.consultation_entitlement_service import (
    _ensure_utc_aware,
    get_valid_consultation_entitlement_by_token,
)

_CORRELATION = re.compile(r"v1\.([A-Za-z0-9_-]{21}[AQgw])\.([A-Za-z0-9_-]{43})")


def correlation_reference(value: str | None) -> str | None:
    match = _CORRELATION.fullmatch(value) if isinstance(value, str) else None
    return match[1] if match else None


def signed_correlation(share_uri: str, reference: str) -> str:
    secret = settings.SECRET_KEY
    if not secret.strip():
        raise CalendlyAPIError("Consultation booking signing is unavailable.")
    message = f"smartbudgetsite:calendly-share:v1\n{share_uri}\n{reference}"
    digest = hmac.digest(secret.encode("utf-8"), message.encode("utf-8"), "sha256")
    tag = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"v1.{reference}.{tag}"


def valid_correlation(value: str | None, entitlement: ConsultationEntitlement) -> bool:
    reference = correlation_reference(value)
    if (
        not reference
        or reference != entitlement.provisioning_reference
        or not entitlement.calendly_share_uri
        or not settings.SECRET_KEY.strip()
    ):
        return False
    return hmac.compare_digest(
        value, signed_correlation(entitlement.calendly_share_uri, reference)
    )


def _share_url(url: str) -> str:
    if (
        not isinstance(url, str)
        or len(url) > 2048
        or re.search(r"[\x00-\x20\\\x7f]", url)
    ):
        raise ValueError("Invalid Share URL.")
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.netloc != "calendly.com"
        or not parts.path.startswith("/d/")
    ):
        raise ValueError("Invalid Share URL.")
    return url


def _booking_redirect(entitlement: ConsultationEntitlement) -> str:
    parts = urlsplit(_share_url(entitlement.calendly_booking_url))
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key != "utm_content"
    ]
    query.append(
        (
            "utm_content",
            signed_correlation(
                entitlement.calendly_share_uri,
                entitlement.provisioning_reference,
            ),
        )
    )
    return urlunsplit(parts._replace(query=urlencode(query)))


def recover_share(event_type: str, marker: str, claimed_at: datetime) -> dict:
    return find_share(
        event_type,
        marker,
        earliest=(claimed_at - timedelta(minutes=2)).isoformat(),
        latest=(datetime.now(UTC) + timedelta(minutes=2)).isoformat(),
    )


def share_details(resource: dict, event_type: str, marker: str) -> tuple[str, str]:
    uri = resource.get("uri")
    resource_path(uri, "shares")
    override = resource.get("share_override")
    links = resource.get("scheduling_links")
    if (
        resource.get("status") != "active"
        or not isinstance(override, dict)
        or override.get("name") != marker
        or not isinstance(links, list)
    ):
        raise CalendlyAPIError("Calendly Share is unavailable.")
    urls = [
        item.get("booking_url")
        for item in links
        if isinstance(item, dict)
        and item.get("owner") == event_type
        and item.get("owner_type") == "EventType"
    ]
    if len(urls) != 1:
        raise CalendlyAPIError("Calendly Share link is ambiguous.")
    return uri, _share_url(urls[0])


def provision_booking_share(db: Session, booking_token: str) -> str:
    if not settings.SECRET_KEY.strip():
        raise CalendlyAPIError("Consultation booking signing is unavailable.")
    with db.begin():
        ConsultationEntitlementRepository.lock_owner_and_entitlement(
            db,
            ConsultationEntitlement.booking_token,
            booking_token,
        )
        entitlement = get_valid_consultation_entitlement_by_token(db, booking_token)
        if entitlement.calendly_share_uri:
            return _booking_redirect(entitlement)
        if not settings.CALENDLY_PERSONAL_ACCESS_TOKEN:
            raise CalendlyAPIError("Calendly access is unavailable.")
        create = entitlement.provisioning_claimed_at is None
        if create:
            event_type = CALENDLY_API_BASE_URL + resource_path(
                settings.CALENDLY_CONSULTATION_EVENT_TYPE_URI,
                "event_types",
            )
            entitlement.calendly_event_type_uri = event_type
            entitlement.provisioning_reference = token_urlsafe(16)
            entitlement.provisioning_claimed_at = datetime.now(UTC)
        event_type = entitlement.calendly_event_type_uri
        marker = f"SmartBudgetSite:{entitlement.provisioning_reference}"
        claimed_at = _ensure_utc_aware(entitlement.provisioning_claimed_at)

    if create:
        try:
            resource = create_share(event_type, marker)
            uri, url = share_details(resource, event_type, marker)
        except (CalendlyAPIError, ValueError):
            uri, url = share_details(
                recover_share(event_type, marker, claimed_at), event_type, marker
            )
    else:
        uri, url = share_details(
            recover_share(event_type, marker, claimed_at), event_type, marker
        )

    with db.begin():
        entitlement = ConsultationEntitlementRepository.lock_owner_and_entitlement(
            db,
            ConsultationEntitlement.booking_token,
            booking_token,
        )
        if entitlement is None:
            raise CalendlyAPIError("Consultation entitlement is unavailable.")
        if entitlement.calendly_share_uri and entitlement.calendly_share_uri != uri:
            raise CalendlyAPIError("Calendly Share recovery is ambiguous.")
        if not entitlement.calendly_share_uri:
            entitlement.calendly_share_uri = uri
            entitlement.calendly_booking_url = url

    # Persist the remote identity even if access expired during the API request.
    with db.begin():
        entitlement = get_valid_consultation_entitlement_by_token(db, booking_token)
        return _booking_redirect(entitlement)
