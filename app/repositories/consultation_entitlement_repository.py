from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload
from typing import cast

from app.models.consultation_entitlement import (
    ConsultationEntitlement,
    ConsultationEntitlementStatus,
)
from app.models.consultation_cancellation import ConsultationCancellation
from app.models.sale_item import SaleItem
from app.models.sale import Sale


class ConsultationEntitlementRepository:
    """Persistence queries for consultation entitlements."""

    @staticmethod
    def cancellation_target_ids(db: Session, invitee_uri: str) -> list[int]:
        return list(db.scalars(
            select(ConsultationCancellation.entitlement_id)
            .where(ConsultationCancellation.invitee_uri == invitee_uri).limit(2)
        ))

    @staticmethod
    def due_share_revocations(db: Session, now: datetime, limit: int) -> list[int]:
        row = ConsultationEntitlement
        return list(db.scalars(
            select(row.id)
            .where(
                or_(row.expires_at <= now, row.cancellation.has()),
                ~row.cancellation.has(ConsultationCancellation.event_uri.is_not(None)),
                row.status != ConsultationEntitlementStatus.BOOKED,
                row.booked_at.is_(None),
                row.provider_event_uri.is_(None),
                row.provider_invitee_uri.is_(None),
                row.calendly_revoked_at.is_(None),
                or_(row.calendly_share_uri.is_not(None), row.provisioning_claimed_at.is_not(None)),
                or_(row.calendly_revoke_outcome.is_(None), row.calendly_revoke_outcome != "provider_booked"),
                or_(row.calendly_revoke_next_at.is_(None), row.calendly_revoke_next_at <= now),
            )
            .order_by(func.coalesce(row.calendly_revoke_next_at, row.expires_at), row.id)
            .limit(limit)
        ))

    @staticmethod
    def lock_owner_and_entitlement(
        db: Session, attribute, value: str,
    ) -> ConsultationEntitlement | None:
        # Match the refund workflow's Sale -> entitlement lock order.
        sale = db.scalar(
            select(Sale)
            .join(SaleItem, SaleItem.sale_id == Sale.id)
            .join(ConsultationEntitlement, ConsultationEntitlement.sale_item_id == SaleItem.id)
            .where(attribute == value)
            .with_for_update(of=Sale)
            .execution_options(populate_existing=True)
        )
        if sale is None:
            return None
        return db.scalar(
            select(ConsultationEntitlement)
            .where(attribute == value)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
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
            .with_for_update()
            .populate_existing()
            .all(),
        )
