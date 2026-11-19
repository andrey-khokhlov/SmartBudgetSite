"""Add consultation capacity state and its notification outbox."""

import sqlalchemy as sa

from alembic import op

revision = "8e21d4f6ab93"
down_revision = "5c2c71bc5f4a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    state = op.create_table(
        "consultation_capacity_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("manually_suspended", sa.Boolean(), nullable=False),
        sa.Column("observed_level", sa.String(9), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_consultation_capacity_singleton"),
        sa.CheckConstraint(
            "observed_level IN ('normal', 'warning', 'exhausted')",
            name="ck_consultation_capacity_observed_level",
        ),
    )
    op.bulk_insert(
        state, [{"id": 1, "manually_suspended": False, "observed_level": "normal"}]
    )
    op.create_table(
        "consultation_capacity_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("episode_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(9), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("channel", sa.String(8), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(24)),
        sa.UniqueConstraint(
            "episode_id", "channel", name="uq_consultation_capacity_channel"
        ),
    )
    op.create_index(
        "ix_consultation_capacity_notification_due",
        "consultation_capacity_notifications",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_table("consultation_capacity_notifications")
    op.drop_table("consultation_capacity_state")
