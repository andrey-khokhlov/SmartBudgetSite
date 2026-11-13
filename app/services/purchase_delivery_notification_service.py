from sqlalchemy.orm import Session

from app.repositories.purchase_delivery_notification_repository import (
    insert_missing_notifications,
)

MAX_INCIDENTS_PER_BATCH = 100


def materialize_purchase_delivery_notifications(
    db: Session, *, limit: int = MAX_INCIDENTS_PER_BATCH
) -> int:
    """Commit one batch and return the count of new channel entries."""
    if not 1 <= limit <= MAX_INCIDENTS_PER_BATCH:
        raise ValueError("Invalid notification materialization batch size.")
    with db.begin():
        return insert_missing_notifications(db, limit=limit)
