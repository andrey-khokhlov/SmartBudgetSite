"""Persist Calendly Share revocation evidence and retry state."""

import sqlalchemy as sa
from alembic import op

revision = "197e36fb4bc1"
down_revision = "6f3c1a8d905e"
branch_labels = None
depends_on = None

TABLE = "consultation_entitlements"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("calendly_revoked_at", sa.DateTime(timezone=True)))
    op.add_column(
        TABLE, sa.Column("calendly_revoke_next_at", sa.DateTime(timezone=True))
    )
    op.add_column(TABLE, sa.Column("calendly_revoke_outcome", sa.String(32)))
    op.add_column(
        TABLE,
        sa.Column(
            "calendly_revoke_attempts", sa.Integer(), nullable=False, server_default="0"
        ),
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM consultation_entitlements "
            "WHERE calendly_revoke_attempts > 0 OR calendly_revoked_at IS NOT NULL)"
        )
    ):
        raise RuntimeError(
            "Downgrade blocked: Calendly revocation evidence would be lost."
        )
    for name in (
        "calendly_revoke_attempts",
        "calendly_revoke_outcome",
        "calendly_revoke_next_at",
        "calendly_revoked_at",
    ):
        op.drop_column(TABLE, name)
