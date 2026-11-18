import re
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.services.calendly import calendly_api_client as api, share_service as shares
from tests.services.test_consultation_entitlement_service import (
    create_test_consultation_entitlement,
)

EVENT_TYPE = "https://api.calendly.com/event_types/TEST"
SHARE = "https://api.calendly.com/shares/TEST"
BOOKING = "https://calendly.com/d/a-b/consultation?utm_source=test&utm_content=obsolete"


def share_resource(marker):
    return {
        "uri": SHARE,
        "status": "active",
        "share_override": {"name": marker},
        "scheduling_links": [
            {"booking_url": BOOKING, "owner": EVENT_TYPE, "owner_type": "EventType"},
        ],
    }


@pytest.fixture
def paid_entitlement(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "secret-for-tests")
    monkeypatch.setattr(settings, "CALENDLY_CONSULTATION_EVENT_TYPE_URI", EVENT_TYPE)
    monkeypatch.setattr(settings, "CALENDLY_PERSONAL_ACCESS_TOKEN", "test-pat")
    entitlement = create_test_consultation_entitlement(db_session)
    db_session.commit()
    db_session.refresh(entitlement)
    token = entitlement.booking_token
    db_session.commit()
    return entitlement, token


def test_create_and_reuse_share_with_pinned_configuration(
    db_session, monkeypatch, paid_entitlement
):
    entitlement, token = paid_entitlement
    create = Mock(side_effect=lambda event_type, marker: share_resource(marker))
    monkeypatch.setattr(shares, "create_share", create)
    target = shares.provision_booking_share(db_session, token)
    monkeypatch.setattr(
        settings, "CALENDLY_CONSULTATION_EVENT_TYPE_URI", EVENT_TYPE + "-OTHER"
    )
    assert shares.provision_booking_share(db_session, token) == target
    db_session.refresh(entitlement)
    create.assert_called_once_with(
        EVENT_TYPE, f"SmartBudgetSite:{entitlement.provisioning_reference}"
    )
    query = parse_qs(urlsplit(target).query)
    assert query["utm_source"] == ["test"]
    assert len(query["utm_content"][0]) == 69
    assert shares.valid_correlation(query["utm_content"][0], entitlement)
    assert token not in target
    assert entitlement.status == "available"


def test_ambiguous_creation_recovers_without_second_post(
    db_session, monkeypatch, paid_entitlement
):
    entitlement, token = paid_entitlement
    create = Mock(side_effect=api.CalendlyAPIError("timeout"))
    recover = Mock(side_effect=api.CalendlyAPIError("not found yet"))
    monkeypatch.setattr(shares, "create_share", create)
    monkeypatch.setattr(shares, "find_share", recover)
    with pytest.raises(api.CalendlyAPIError):
        shares.provision_booking_share(db_session, token)
    db_session.refresh(entitlement)
    assert entitlement.provisioning_claimed_at is not None
    marker = f"SmartBudgetSite:{entitlement.provisioning_reference}"
    db_session.commit()
    recover.side_effect = None
    recover.return_value = share_resource(marker)
    monkeypatch.setattr(
        settings, "CALENDLY_CONSULTATION_EVENT_TYPE_URI", EVENT_TYPE + "-OTHER"
    )
    assert shares.provision_booking_share(db_session, token).startswith(
        "https://calendly.com/d/"
    )
    assert recover.call_args.args == (EVENT_TYPE, marker)
    create.assert_called_once()


def test_database_failure_after_create_leaves_claim(
    db_session, monkeypatch, paid_entitlement
):
    _, token = paid_entitlement
    create = Mock(side_effect=lambda event_type, marker: share_resource(marker))
    monkeypatch.setattr(shares, "create_share", create)

    def reject_share_write(session, *_):
        if any(getattr(row, "calendly_share_uri", None) for row in session.dirty):
            raise IntegrityError("write", {}, Exception())

    event.listen(db_session, "before_flush", reject_share_write)
    try:
        with pytest.raises(IntegrityError):
            shares.provision_booking_share(db_session, token)
    finally:
        event.remove(db_session, "before_flush", reject_share_write)
    monkeypatch.setattr(
        shares, "find_share", lambda event_type, marker, **_: share_resource(marker)
    )
    assert shares.provision_booking_share(db_session, token).startswith(
        "https://calendly.com/d/"
    )
    create.assert_called_once()


@pytest.mark.parametrize("count", [0, 1, 2])
def test_listing_requires_one_match_across_all_pages(monkeypatch, count):
    visited = []
    candidates = [share_resource("match")] * count
    monkeypatch.setattr(
        api, "get_resource", lambda path: {"uri": "https://api.calendly.com/users/TEST"}
    )

    def listing(method, path, *, params):
        visited.append(params.copy())
        if "page_token" not in params:
            return {
                "collection": candidates[:1],
                "pagination": {"next_page_token": "second"},
            }
        return {"collection": candidates[1:], "pagination": {"next_page_token": None}}

    monkeypatch.setattr(api, "api_request", listing)
    if count == 1:
        assert (
            api.find_share(EVENT_TYPE, "match", earliest="start", latest="end")["uri"]
            == SHARE
        )
    else:
        with pytest.raises(api.CalendlyAPIError):
            api.find_share(EVENT_TYPE, "match", earliest="start", latest="end")
    assert [page.get("page_token") for page in visited] == [None, "second"]
    assert all(page["event_type"] == EVENT_TYPE for page in visited)


@pytest.mark.parametrize("lang", ["en", "ru"])
def test_protected_post_requires_csrf_and_redirects(
    client, monkeypatch, paid_entitlement, lang
):
    _, token = paid_entitlement
    create = Mock(side_effect=lambda event_type, marker: share_resource(marker))
    monkeypatch.setattr(shares, "create_share", create)
    path = f"/consultation/book/{token}?lang={lang}"
    page = client.get(path)
    assert page.status_code == 200
    invalid = client.post(path)
    assert invalid.status_code == 403
    assert ("Reopen" if lang == "en" else "Откройте ссылку") in invalid.text
    create.assert_not_called()
    form = dict(re.findall(r'name="(csrf_\w+)" value="([0-9a-f]+)"', page.text))
    reply = client.post(path, data=form, follow_redirects=False)
    assert reply.status_code == 303
    assert reply.headers["cache-control"] == "private, no-store, max-age=0"
    assert reply.headers["referrer-policy"] == "no-referrer"
    assert reply.headers["location"].startswith("https://calendly.com/d/")
    assert token not in reply.headers["location"]


def test_provider_failure_returns_sanitized_error(client, monkeypatch, paid_entitlement):
    _, token = paid_entitlement
    error = api.CalendlyAPIError("sensitive provider diagnostic")
    monkeypatch.setattr(shares, "create_share", Mock(side_effect=error))
    monkeypatch.setattr(shares, "find_share", Mock(side_effect=error))
    path = f"/consultation/book/{token}?lang=en"
    page = client.get(path)
    form = dict(re.findall(r'name="(csrf_\w+)" value="([0-9a-f]+)"', page.text))
    response = client.post(path, data=form)
    assert response.status_code == 503
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "temporarily unavailable" in response.text
    assert all(
        value not in response.text
        for value in (token, str(error), settings.SECRET_KEY, settings.CALENDLY_PERSONAL_ACCESS_TOKEN)
    )
