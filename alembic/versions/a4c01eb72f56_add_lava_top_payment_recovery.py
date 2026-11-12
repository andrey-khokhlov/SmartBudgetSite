"""Add automatic Lava.top payment recovery state."""

import sqlalchemy as sa
from alembic import op

revision = "a4c01eb72f56"
down_revision = "0e21d8842f61"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lava_top_payment_recovery",
        sa.Column("sale_id", sa.Integer(), primary_key=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_outcome", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["sale_id"], ["sales.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "lava_top_recovery_cooldown",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consecutive_provider_failures", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("lava_top_recovery_cooldown")
    op.drop_table("lava_top_payment_recovery")
