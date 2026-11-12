"""Store purchase language after verifying the email cutover boundary."""

import sqlalchemy as sa
from alembic import op

revision = "eb63c5a92f10"
down_revision = "4b1e9d62c730"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("LOCK TABLE purchase_email_deliveries IN SHARE ROW EXCLUSIVE MODE")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM purchase_email_deliveries WHERE status = 'sending') THEN
                RAISE EXCEPTION 'Reconcile sending purchase emails before the G13 template cutover';
            END IF;
        END $$;
        """)
    op.add_column(
        "sales",
        sa.Column(
            "purchase_language", sa.String(2), server_default="en", nullable=False
        ),
    )
    op.create_check_constraint(
        "ck_sales_purchase_language", "sales", "purchase_language IN ('ru', 'en')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_sales_purchase_language", "sales", type_="check")
    op.drop_column("sales", "purchase_language")
