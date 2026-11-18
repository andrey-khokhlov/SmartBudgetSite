import enum
import uuid
from datetime import datetime, UTC

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class ConsultationEntitlementStatus(str, enum.Enum):
    """
    Consultation entitlement lifecycle status.

    Business rules:
    - available: customer can access the booking flow while token is not expired.
    - booked: consultation slot was booked; token must no longer allow booking.
    - expired: booking window has passed.
    - cancelled: entitlement was cancelled manually or by future business logic.

    Side effects:
    - Status itself does not trigger Calendly actions.
    - Booking provider integration should update this status through service logic.

    Invariants/restrictions:
    - Only these values are valid entitlement statuses.
    """

    AVAILABLE = "available"
    BOOKED = "booked"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ConsultationEntitlement(Base):
    """
    Backend-owned access right for booking one consultation.

    Business rules:
    - Each entitlement belongs to one purchased consultation SaleItem.
    - booking_token is the public single-use access token for booking page.
    - expires_at controls how long the customer may access booking.
    - booked_at is set only after successful booking confirmation.

    Side effects:
    - Creating this row gives the customer booking access.
    - It does not create a Calendly booking by itself.

    Invariants/restrictions:
    - booking_token must be unique.
    - status must be one of ConsultationEntitlementStatus values.
    - sale_item_id is unique for MVP: one consultation SaleItem gives one entitlement.
    """

    __tablename__ = "consultation_entitlements"

    id: Mapped[int] = mapped_column(primary_key=True)

    sale_item_id: Mapped[int] = mapped_column(
        ForeignKey("sale_items.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    booking_token: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        unique=True,
        index=True,
        default=lambda: str(uuid.uuid4()),
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=ConsultationEntitlementStatus.AVAILABLE.value,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    booked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    booking_provider: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    provider_event_uri: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    provider_invitee_uri: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    provisioning_reference: Mapped[str | None] = mapped_column(String(22))
    provisioning_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calendly_event_type_uri: Mapped[str | None] = mapped_column(String(500))
    calendly_share_uri: Mapped[str | None] = mapped_column(String(500))
    calendly_booking_url: Mapped[str | None] = mapped_column(String(2048))
    calendly_revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calendly_revoke_next_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calendly_revoke_attempts: Mapped[int] = mapped_column(server_default="0")
    calendly_revoke_outcome: Mapped[str | None] = mapped_column(String(32))

    sale_item = relationship(
        "SaleItem",
        back_populates="consultation_entitlement",
    )

    __table_args__ = (
        UniqueConstraint(
            "provisioning_reference",
            name="uq_consultation_entitlements_provisioning_reference",
        ),
        UniqueConstraint(
            "calendly_share_uri", name="uq_consultation_entitlements_calendly_share_uri",
        ),
        CheckConstraint(
            status.in_(
                [
                    ConsultationEntitlementStatus.AVAILABLE.value,
                    ConsultationEntitlementStatus.BOOKED.value,
                    ConsultationEntitlementStatus.EXPIRED.value,
                    ConsultationEntitlementStatus.CANCELLED.value,
                ]
            ),
            name="ck_consultation_entitlements_status",
        ),
        Index(
            "uq_consultation_entitlements_provider_event_uri",
            "provider_event_uri",
            unique=True,
            postgresql_where=provider_event_uri.isnot(None),
        ),
    )
