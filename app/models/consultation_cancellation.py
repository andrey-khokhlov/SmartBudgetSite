from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ConsultationCancellation(Base):
    __tablename__ = "consultation_cancellations"

    entitlement_id: Mapped[int] = mapped_column(
        ForeignKey("consultation_entitlements.id", ondelete="RESTRICT"), primary_key=True
    )
    refund_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("refund_requests.id", ondelete="RESTRICT")
    )
    access_closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_uri: Mapped[str | None] = mapped_column(String(500))
    invitee_uri: Mapped[str | None] = mapped_column(String(500))
    provider_outcome: Mapped[str | None] = mapped_column(String(32))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
