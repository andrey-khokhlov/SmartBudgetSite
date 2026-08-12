from datetime import datetime

from sqlalchemy.orm import Session, joinedload
from typing import cast

from app.models.consultation_entitlement import (
    ConsultationEntitlement,
    ConsultationEntitlementStatus,
)
from app.models.sale_item import SaleItem


class ConsultationEntitlementRepository:
    """
    Repository for consultation entitlement persistence queries.

    Business rules:
    - Repository only loads entitlement data.
    - Booking lifecycle decisions belong to service layer.

    Side effects:
    - Executes read queries against the database.

    Invariants/restrictions:
    - Do not place status transition logic here.
    """

    @staticmethod
    def get_by_provider_event_uri(
        db: Session,
        provider_event_uri: str,
    ) -> ConsultationEntitlement | None:
        """
        Find consultation entitlement by external provider event URI.

        Business rules:
        - Used for future webhook reconciliation.
        - Provider event URI should identify the external booking event.

        Side effects:
        - Executes one database query.

        Invariants/restrictions:
        - Does not validate status.
        - Does not mutate entitlement.
        """

        return (
            db.query(ConsultationEntitlement)
            .filter(
                ConsultationEntitlement.provider_event_uri == provider_event_uri,
            )
            .one_or_none()
        )

    @staticmethod
    def get_all_with_sale_data(
            db: Session,
            status: str | None = None,
            limit: int = 50,
            offset: int = 0,
    ) -> list[ConsultationEntitlement]:
        """
        Load consultation entitlements with related sale data.

        Business rules:
        - Used for admin visibility and operational support.
        - Includes related SaleItem and Sale relations.
        - Optional status filter is applied at query level.

        Side effects:
        - Executes read query with eager loading.

        Invariants/restrictions:
        - Does not mutate lifecycle state.
        """

        query = (
            db.query(ConsultationEntitlement)
            .options(
                joinedload(ConsultationEntitlement.sale_item).joinedload(
                    SaleItem.sale
                )
            )
        )

        if status:
            query = query.filter(ConsultationEntitlement.status == status)

        query = (
            query
            .order_by(ConsultationEntitlement.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        return cast(
            list[ConsultationEntitlement],
            query.all(),
        )

    @staticmethod
    def list_due_available(
        db: Session,
        *,
        expires_at_or_before: datetime,
    ) -> list[ConsultationEntitlement]:
        """Load every available entitlement whose booking window has elapsed."""
        return cast(
            list[ConsultationEntitlement],
            db.query(ConsultationEntitlement)
            .filter(
                ConsultationEntitlement.status
                == ConsultationEntitlementStatus.AVAILABLE.value,
                ConsultationEntitlement.expires_at <= expires_at_or_before,
            )
            .order_by(ConsultationEntitlement.id)
            .all(),
        )
