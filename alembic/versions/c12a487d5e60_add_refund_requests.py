"""Persist customer refund requests separately from refund operations."""

import sqlalchemy as sa
from alembic import op

revision = "c12a487d5e60"
down_revision = "8c40f6a2e517"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refund_requests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("submission_token", sa.String(64), nullable=False),
        sa.Column(
            "sale_id",
            sa.Integer,
            sa.ForeignKey("sales.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("purchase_reference", sa.String(18), nullable=False),
        sa.Column("customer_email", sa.String(200), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("language", sa.String(2), nullable=False),
        sa.Column("message", sa.Text, nullable=True),
        sa.Column("composition", sa.String(16), nullable=False),
        sa.Column("window_status", sa.String(16), nullable=True),
        sa.Column("window_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.UniqueConstraint(
            "submission_token", name="uq_refund_requests_submission_token"
        ),
    )
    op.create_index("ix_refund_requests_sale_id", "refund_requests", ["sale_id"])


def downgrade() -> None:
    op.execute("LOCK TABLE refund_requests IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM refund_requests) THEN
                RAISE EXCEPTION 'Downgrade blocked: customer refund requests would be lost.';
            END IF;
        END $$;
    """)
    op.drop_table("refund_requests")
