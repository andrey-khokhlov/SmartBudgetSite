"""Record operator response and closure for refund requests."""

import sqlalchemy as sa
from alembic import op

revision = "6e4f8c2a9b17"
down_revision = "1c6ea8b50d37"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "refund_requests", sa.Column("first_responded_at", sa.DateTime(timezone=True))
    )
    op.add_column("refund_requests", sa.Column("closed_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_refund_requests_lifecycle",
        "refund_requests",
        "(status = 'pending' AND first_responded_at IS NULL AND closed_at IS NULL) OR "
        "(status = 'responded' AND first_responded_at IS NOT NULL AND closed_at IS NULL) OR "
        "(status = 'closed' AND first_responded_at IS NOT NULL AND closed_at IS NOT NULL)",
    )


def downgrade() -> None:
    op.execute("LOCK TABLE refund_requests IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM refund_requests WHERE first_responded_at IS NOT NULL) THEN
                RAISE EXCEPTION 'Downgrade blocked: refund request lifecycle history exists.';
            END IF;
        END $$;
    """)
    op.drop_constraint("ck_refund_requests_lifecycle", "refund_requests", type_="check")
    op.drop_column("refund_requests", "closed_at")
    op.drop_column("refund_requests", "first_responded_at")
