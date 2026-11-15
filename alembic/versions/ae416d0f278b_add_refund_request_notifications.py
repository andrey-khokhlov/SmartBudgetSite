"""Add the refund request operator notification outbox."""

import sqlalchemy as sa
from alembic import op

revision = "ae416d0f278b"
down_revision = "c12a487d5e60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refund_request_notifications",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "request_id",
            sa.Integer,
            sa.ForeignKey("refund_requests.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(8), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("attempt_count", sa.Integer, nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(24)),
        sa.UniqueConstraint("request_id", "channel", name="uq_refund_request_channel"),
    )
    op.create_index(
        "ix_refund_request_notification_due",
        "refund_request_notifications",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.execute("LOCK TABLE refund_request_notifications IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM refund_request_notifications) THEN
                RAISE EXCEPTION 'Downgrade blocked: refund notification history would be lost.';
            END IF;
        END $$;
    """)
    op.drop_table("refund_request_notifications")
