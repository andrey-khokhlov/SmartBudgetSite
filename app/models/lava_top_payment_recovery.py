from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class LavaTopPaymentRecovery(Base):
    """Latest automatic lookup and retry state for one Sale."""

    __tablename__ = "lava_top_payment_recovery"

    sale_id: Mapped[int] = mapped_column(
        ForeignKey("sales.id", ondelete="CASCADE"), primary_key=True
    )
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_outcome: Mapped[str] = mapped_column(String(32))


class LavaTopRecoveryCooldown(Base):
    """Provider-wide pause shared by recovery passes."""

    __tablename__ = "lava_top_recovery_cooldown"

    id: Mapped[int] = mapped_column(primary_key=True)
    until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consecutive_provider_failures: Mapped[int]
