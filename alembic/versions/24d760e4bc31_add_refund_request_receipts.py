"""Persist customer refund request receipts."""

import sqlalchemy as sa
from alembic import op

revision = "24d760e4bc31"
down_revision = "ae416d0f278b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refund_request_receipts",
        sa.Column(
            "request_id",
            sa.Integer,
            sa.ForeignKey("refund_requests.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("attempt_count", sa.Integer, nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("sending_started_at", sa.DateTime(timezone=True)),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("failure_classification", sa.String(16)),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'accepted', 'failed')",
            name="ck_refund_request_receipt_status",
        ),
        sa.CheckConstraint(
            "attempt_count BETWEEN 0 AND 7", name="ck_refund_request_receipt_attempts"
        ),
    )
    op.create_index(
        "ix_refund_request_receipt_due",
        "refund_request_receipts",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.execute("LOCK TABLE refund_request_receipts IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM refund_request_receipts) THEN
                RAISE EXCEPTION 'Downgrade blocked: refund receipt history would be lost.';
            END IF;
        END $$;
    """)
    op.drop_table("refund_request_receipts")
