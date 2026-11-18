import re

import httpx
from fastapi import HTTPException

from app.core.config import settings


CALENDLY_API_BASE_URL = "https://api.calendly.com"
_API_RESOURCE = re.compile(
    r"/(?:event_types|shares|users|scheduled_events)/[A-Za-z0-9_-]{1,80}"
    r"(?:/invitees/[A-Za-z0-9_-]{1,80})?"
)


class CalendlyAPIError(Exception):
    """A sanitized failure to obtain a verified Calendly response."""


def resource_path(uri: str, collection: str) -> str:
    if not isinstance(uri, str) or not uri.startswith(CALENDLY_API_BASE_URL):
        raise ValueError("Invalid Calendly resource URI.")
    path = uri[len(CALENDLY_API_BASE_URL):].removeprefix("/api/v2")
    if not _API_RESOURCE.fullmatch(path) or not path.startswith(f"/{collection}/"):
        raise ValueError("Invalid Calendly resource URI.")
    if path.count("/") != 2:
        raise ValueError("Invalid Calendly resource URI.")
    return path


def invitee_path(uri: str) -> str:
    if not isinstance(uri, str) or not uri.startswith(CALENDLY_API_BASE_URL):
        raise ValueError("Invalid Calendly invitee URI.")
    path = uri[len(CALENDLY_API_BASE_URL):].removeprefix("/api/v2")
    if (
        not _API_RESOURCE.fullmatch(path)
        or not path.startswith("/scheduled_events/")
        or path.count("/") != 4
    ):
        raise ValueError("Invalid Calendly invitee URI.")
    return path


def api_request(method: str, path: str, *, expected_status: int = 200, **kwargs) -> dict:
    token = settings.CALENDLY_PERSONAL_ACCESS_TOKEN
    if not token:
        raise CalendlyAPIError("Calendly access is unavailable.")
    try:
        response = httpx.request(
            method,
            CALENDLY_API_BASE_URL + path,
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
            follow_redirects=False,
            **kwargs,
        )
        if response.status_code == expected_status:
            payload = response.json()
            if isinstance(payload, dict):
                return payload
    except (httpx.HTTPError, ValueError):
        pass
    raise CalendlyAPIError("Calendly request could not be verified.")


def get_resource(path: str) -> dict:
    resource = api_request("GET", path).get("resource")
    if not isinstance(resource, dict):
        raise CalendlyAPIError("Calendly resource is unavailable.")
    return resource


def create_share(event_type: str, marker: str) -> dict:
    resource = api_request(
        "POST", "/shares", expected_status=201,
        json={"event_type": event_type, "name": marker},
    ).get("resource")
    if not isinstance(resource, dict):
        raise CalendlyAPIError("Calendly Share is unavailable.")
    return resource


def find_share(event_type: str, marker: str, *, earliest: str, latest: str) -> dict:
    user = get_resource("/users/me").get("uri")
    resource_path(user, "users")
    params = {
        "user": user, "event_type": event_type, "count": 100,
        "min_created_at": earliest, "max_created_at": latest,
    }
    match = None
    seen_tokens = set()
    for _ in range(10):
        page = api_request("GET", "/shares", params=params)
        collection, pagination = page.get("collection"), page.get("pagination")
        if not isinstance(collection, list) or not isinstance(pagination, dict):
            break
        for share in collection:
            if not isinstance(share, dict) or not isinstance(share.get("share_override"), dict):
                raise CalendlyAPIError("Calendly Share listing is incomplete.")
            if share["share_override"].get("name") == marker:
                if match is not None:
                    raise CalendlyAPIError("Calendly Share recovery is ambiguous.")
                match = share
        next_token = pagination.get("next_page_token")
        if next_token is None and not pagination.get("next_page"):
            if match is not None:
                return match
            break
        if not isinstance(next_token, str) or not next_token or next_token in seen_tokens:
            break
        seen_tokens.add(next_token)
        params["page_token"] = next_token
    raise CalendlyAPIError("Calendly Share recovery could not be verified.")


def get_current_user() -> dict:
    """
    Retrieve current Calendly user profile using Personal Access Token.

    Raises:
    - HTTPException when Calendly API token is missing.
    - HTTPException when Calendly API request fails.
    """

    if not settings.CALENDLY_PERSONAL_ACCESS_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="Calendly Personal Access Token is not configured.",
        )

    try:
        response = httpx.get(
            f"{CALENDLY_API_BASE_URL}/users/me",
            headers={
                "Authorization": (
                    f"Bearer {settings.CALENDLY_PERSONAL_ACCESS_TOKEN}"
                ),
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="Calendly API request failed.",
        ) from exc

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail="Calendly API request failed.",
        ) from exc

    return response.json()


def list_webhook_subscriptions() -> dict:
    """
    Retrieve Calendly webhook subscriptions for the current organization.

    Raises:
    - HTTPException when Calendly API token is missing.
    - HTTPException when Calendly API request fails.
    """

    current_user = get_current_user()
    organization_uri = current_user["resource"]["current_organization"]

    try:
        response = httpx.get(
            f"{CALENDLY_API_BASE_URL}/webhook_subscriptions",
            params={
                "organization": organization_uri,
                "scope": "organization",
            },
            headers={
                "Authorization": (
                    f"Bearer {settings.CALENDLY_PERSONAL_ACCESS_TOKEN}"
                ),
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )

        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="Calendly webhook subscriptions request failed.",
        ) from exc

    return response.json()
