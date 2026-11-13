from datetime import UTC, datetime

import pytest
from sqlalchemy import event, select

from app.models.purchase_delivery_incident import PurchaseDeliveryIncident
from app.models.purchase_delivery_notification import PurchaseDeliveryNotification
from app.repositories.resend_webhook_repository import add_operator_incident
from app.services.purchase_delivery_notification_service import (
    materialize_purchase_delivery_notifications as materialize,
)


def test_materializes_bounded_pairs_including_resend_incidents(db_session):
    now = datetime.now(UTC)
    incident = PurchaseDeliveryIncident(
        sale_id=1,
        subject_id=1,
        kind="email_provider_delayed",
        severity="warning",
        first_detected_at=now,
        last_observed_at=now,
    )
    db_session.add(incident)
    db_session.flush()
    incident_id = incident.id
    add_operator_incident(
        db_session,
        sale_id=2,
        delivery_id=2,
        kind="email_provider_bounced",
        event_id="msg_test",
        now=now,
    )
    db_session.commit()

    assert materialize(db_session, limit=1) == 2
    smtp, telegram = db_session.scalars(
        select(PurchaseDeliveryNotification).order_by(
            PurchaseDeliveryNotification.channel
        )
    ).all()
    assert [smtp.channel, telegram.channel] == ["smtp", "telegram"]
    assert smtp.id != telegram.id
    assert smtp.incident_id == telegram.incident_id == incident_id
    smtp.attempt_count = 1
    smtp.last_attempt_at = now
    smtp.delivered_at = now
    db_session.commit()

    assert materialize(db_session, limit=1) == 2
    assert materialize(db_session, limit=1) == 0
    assert smtp.attempt_count == 1 and smtp.delivered_at is not None
    assert telegram.attempt_count == 0 and telegram.delivered_at is None
    operator = db_session.scalar(
        select(PurchaseDeliveryIncident).where(
            PurchaseDeliveryIncident.originating_event_id == "msg_test"
        )
    )
    assert set(
        db_session.scalars(
            select(PurchaseDeliveryNotification.channel).where(
                PurchaseDeliveryNotification.incident_id == operator.id
            )
        )
    ) == {"smtp", "telegram"}


@pytest.mark.parametrize("existing_channel", [None, "smtp", "telegram"])
def test_resolved_incident_receives_no_new_entries(db_session, existing_channel):
    now = datetime.now(UTC)
    incident = PurchaseDeliveryIncident(
        sale_id=1,
        subject_id=1,
        kind="email_failed",
        severity="error",
        first_detected_at=now,
        last_observed_at=now,
    )
    db_session.add(incident)
    db_session.flush()
    if existing_channel is not None:
        db_session.add(
            PurchaseDeliveryNotification(
                incident_id=incident.id,
                channel=existing_channel,
                attempt_count=1,
                delivered_at=now,
            )
        )
    db_session.commit()
    incident.resolved_at = now
    db_session.commit()

    assert materialize(db_session) == 0
    assert materialize(db_session) == 0
    entries = db_session.scalars(select(PurchaseDeliveryNotification)).all()
    if existing_channel is None:
        assert entries == []
    else:
        (entry,) = entries
        assert entry.channel == existing_channel
        assert entry.attempt_count == 1
        assert entry.delivered_at.replace(tzinfo=UTC) == now


def test_commit_failure_rolls_back_both_channels(db_session):
    now = datetime.now(UTC)
    db_session.add(
        PurchaseDeliveryIncident(
            sale_id=1,
            subject_id=1,
            kind="email_failed",
            severity="error",
            first_detected_at=now,
            last_observed_at=now,
        )
    )
    db_session.commit()

    def fail_commit(session):
        assert len(session.scalars(select(PurchaseDeliveryNotification)).all()) == 2
        raise RuntimeError("test commit failure")

    event.listen(db_session, "before_commit", fail_commit, once=True)
    with pytest.raises(RuntimeError, match="test commit failure"):
        materialize(db_session)
    assert db_session.scalars(select(PurchaseDeliveryNotification)).all() == []
    db_session.rollback()
    assert materialize(db_session) == 2
