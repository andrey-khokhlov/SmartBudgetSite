"""Record the verification method for new full-Sale refund confirmations."""

import sqlalchemy as sa

from alembic import op

revision = "1c6ea8b50d37"
down_revision = "4a2d8c71ef36"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "refund_operations",
        sa.Column("confirmation_method", sa.String(32), nullable=True),
    )
    op.create_check_constraint(
        "ck_refund_operations_confirmation_method",
        "refund_operations",
        "confirmation_method IS NULL OR (status = 'confirmed' AND "
        "confirmation_method IN ('original_provider', 'alternative_transfer'))",
    )


def downgrade() -> None:
    op.execute("LOCK TABLE refund_operations IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM refund_operations WHERE confirmation_method IS NOT NULL) THEN
                RAISE EXCEPTION 'Downgrade blocked: refund confirmation method history exists.';
            END IF;
        END $$;
        """)
    op.drop_constraint(
        "ck_refund_operations_confirmation_method", "refund_operations", type_="check"
    )
    op.drop_column("refund_operations", "confirmation_method")
