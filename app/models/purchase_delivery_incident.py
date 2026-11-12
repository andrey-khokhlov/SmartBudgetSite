from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, String, false
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PurchaseDeliveryIncident(Base):
    """One observed episode of a purchase delivery problem."""

    __tablename__ = "purchase_delivery_incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Retain incident history if the source records are removed.
    sale_id: Mapped[int] = mapped_column()
    subject_id: Mapped[int] = mapped_column()
    kind: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(8))
    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requires_operator: Mapped[bool] = mapped_column(Boolean, server_default=false())
    originating_event_id: Mapped[str | None] = mapped_column(String(128))
    resolved_by: Mapped[str | None] = mapped_column(String(128))
    resolution_reason: Mapped[str | None] = mapped_column(String(1000))

    __table_args__ = (
        CheckConstraint(
            "severity IN ('error', 'warning')",
            name="ck_purchase_delivery_incidents_severity",
        ),
        Index(
            "uq_purchase_delivery_incidents_open",
            sale_id,
            subject_id,
            kind,
            unique=True,
            postgresql_where=resolved_at.is_(None) & requires_operator.is_(False),
            sqlite_where=resolved_at.is_(None) & requires_operator.is_(False),
        ),
        Index(
            "uq_purchase_delivery_incidents_origin",
            sale_id,
            subject_id,
            kind,
            originating_event_id,
            unique=True,
        ),
    )
