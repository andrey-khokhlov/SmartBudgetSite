"""Add purchase-email failure classification."""

import sqlalchemy as sa
from alembic import op

revision = "78e0b9842bd1"
down_revision = "c20d9be51072"
branch_labels = None
depends_on = None

TABLE = "purchase_email_deliveries"
CONSTRAINT = "ck_purchase_email_deliveries_failure_classification"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("failure_classification", sa.String(16)))
    op.create_check_constraint(
        CONSTRAINT,
        TABLE,
        "failure_classification IN ('transient', 'permanent', 'unknown')",
    )
    op.execute(
        "UPDATE purchase_email_deliveries SET failure_classification = 'unknown' "
        "WHERE status = 'failed'"
    )


def downgrade() -> None:
    op.execute("LOCK TABLE purchase_email_deliveries IN ACCESS EXCLUSIVE MODE")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM purchase_email_deliveries
                WHERE failure_classification IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'Downgrade blocked: purchase email failure classifications would be lost.'
                    USING HINT = 'Keep this revision or archive and explicitly migrate the classifications before downgrading.';
            END IF;
        END $$;
        """
    )
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.drop_column(TABLE, "failure_classification")
