from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ResendWebhookEvent(Base):
    __tablename__ = "resend_webhook_events"

    svix_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_type: Mapped[str | None] = mapped_column(String(32))
    provider_email_id: Mapped[str | None] = mapped_column(String(255))
    delivery_id: Mapped[int | None]
    provider_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(40))

    __table_args__ = (
        Index("ix_resend_webhook_events_delivery_outcome", "delivery_id", "outcome"),
        Index("ix_resend_webhook_events_first_received_at", "first_received_at"),
    )
