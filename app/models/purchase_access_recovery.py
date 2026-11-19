from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RecoveryDeliveryStatus(StrEnum):
    READY = "ready"
    SENDING = "sending"
    ACCEPTED = "accepted"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"
    RECONCILIATION_REQUIRED = "reconciliation_required"


class PurchaseAccessRecovery(Base):
    """Audit of one download reissue and its independently controlled delivery."""

    __tablename__ = "purchase_access_recoveries"
    __table_args__ = (
        UniqueConstraint(
            "sale_id", "request_id", name="uq_purchase_access_recovery_request"
        ),
        CheckConstraint(
            "delivery_status IN ('ready', 'sending', 'accepted', 'failed', "
            "'ambiguous', 'reconciliation_required')",
            name="ck_purchase_access_recovery_delivery_status",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND previous_attempt_count >= 0",
            name="ck_purchase_access_recovery_attempt_counts",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(
        ForeignKey("sales.id", ondelete="RESTRICT"), index=True
    )
    entitlement_id: Mapped[int] = mapped_column(
        ForeignKey("download_entitlements.id", ondelete="RESTRICT")
    )
    request_id: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(500))
    verification_method: Mapped[str] = mapped_column(String(32))
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    previous_email: Mapped[str | None] = mapped_column(String(200))
    recipient: Mapped[str] = mapped_column(String(200))

    previous_status: Mapped[str] = mapped_column(String(20))
    previous_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    previous_attempt_count: Mapped[int] = mapped_column()
    previous_first_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    previous_last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    delivery_status: Mapped[str] = mapped_column(
        String(32), default=RecoveryDeliveryStatus.READY
    )
    attempt_count: Mapped[int] = mapped_column(default=0)
    first_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload_fingerprint: Mapped[str | None] = mapped_column(String(64))
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(32))
