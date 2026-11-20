"""Persist separate operator reminder cycles for refund requests."""

import sqlalchemy as sa
from alembic import op

revision = "9f3b1a7c2d84"
down_revision = "6e4f8c2a9b17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refund_request_reminders",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "request_id",
            sa.Integer,
            sa.ForeignKey("refund_requests.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("cycle_date", sa.Date, nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("telegram_attempts", sa.Integer, nullable=False),
        sa.Column("smtp_attempts", sa.Integer, nullable=False),
        sa.Column("telegram_due_at", sa.DateTime(timezone=True)),
        sa.Column("smtp_due_at", sa.DateTime(timezone=True)),
        sa.Column("claim_channel", sa.String(8)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(24)),
        sa.UniqueConstraint(
            "request_id", "cycle_date", name="uq_refund_request_reminder_cycle"
        ),
    )
    op.create_index(
        "ix_refund_request_reminders_status_cycle",
        "refund_request_reminders",
        ["status", "cycle_date"],
    )


def downgrade() -> None:
    op.execute("LOCK TABLE refund_request_reminders IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM refund_request_reminders) THEN
                RAISE EXCEPTION 'Downgrade blocked: refund request reminder history exists.';
            END IF;
        END $$;
    """)
    op.drop_table("refund_request_reminders")
